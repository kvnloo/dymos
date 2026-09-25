"""AI-assisted fork diagnostic for Dymos #1239; no optimizer or flight simulation.

Execute baseline and candidate in separate processes. Candidate patching is
runner-local and guarded by the exact phase.py blob. Green baseline means the
specified failures reproduced alongside passing controls, not that Dymos passed.
"""
import difflib
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import traceback

PIN = '5bfbe394d251b5b7ccf510109648d576ecf4d390'
BLOB = 'eda45bcb676e4c42c49ba8ef796e165a95401972'
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'diagnostic-results'
OUT.mkdir(exist_ok=True)
os.environ['OPENMDAO_REPORTS'] = '0'


def patch():
    path = ROOT / 'dymos/phase/phase.py'
    raw = path.read_bytes()
    digest = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    if digest != BLOB:
        raise RuntimeError(f'Unexpected phase.py blob: {digest}')
    old = raw.decode()
    new = old.replace('from openmdao.recorders.case import Case\n',
                      'from openmdao.recorders.case import Case\nfrom openmdao.utils.units import convert_units\n')
    needle = "                    prev_state_val = prev_state_val.clip(options['lower'], options['upper'])"
    if new.count(needle) != 1:
        raise RuntimeError('State clipping patch target was not unique')
    replacement = '''                    lower = (None if options['lower'] is None else
                             convert_units(options['lower'], options['units'], prev_state_units))
                    upper = (None if options['upper'] is None else
                             convert_units(options['upper'], options['units'], prev_state_units))
                    prev_state_val = prev_state_val.clip(lower, upper)'''
    new = new.replace(needle, replacement)
    path.write_text(new)
    (OUT / 'candidate.patch').write_text(''.join(difflib.unified_diff(
        old.splitlines(True), new.splitlines(True),
        fromfile='a/dymos/phase/phase.py', tofile='b/dymos/phase/phase.py')))
    print('Applied runner-local state-only candidate; control path unchanged.')


def run(variant):
    import numpy as np
    import dymos as dm
    import openmdao
    import openmdao.api as om

    # name, declared units, recorder units, endpoints, lower, upper, expected baseline pass
    cases = [
        ('same_units_control', 'rad', 'rad', (0., .05), -.15, .15, True),
        ('degrees_bounded', 'rad', 'deg', (0., .05), -.15, .15, False),
        ('degrees_unbounded_control', 'rad', 'deg', (0., .05), None, None, True),
        ('degrees_lower_only', 'rad', 'deg', (-.05, 0.), -.15, None, False),
        ('degrees_upper_only', 'rad', 'deg', (0., .05), None, .15, False),
        ('temperature_offset', 'K', 'degC', (290., 300.), 280., 320., False),
        ('temperature_lower_only', 'K', 'degC', (290., 300.), 280., None, False),
        ('real_clipping_control', 'rad', 'rad', (.2, .2), None, .15, True),
    ]
    receipt = {'source_pin': PIN, 'variant': variant, 'dymos': dm.__version__,
               'openmdao': openmdao.__version__, 'cases': [],
               'scope': 'Real record/load_case pipeline; no optimizer, no ODE integration, no flight model.'}
    for name, unit, recorded, values, lower, upper, baseline_pass in cases:
        item = {'case': name, 'declared_units': unit, 'recorded_units': recorded}
        with tempfile.TemporaryDirectory(prefix='dymos-1239-') as directory:
            before = Path.cwd()
            os.chdir(directory)
            problems = []
            try:
                class RateODE(om.ExplicitComponent):
                    def initialize(self):
                        self.options.declare('num_nodes', types=int)

                    def setup(self):
                        n = self.options['num_nodes']
                        self.add_input('q', shape=(n,), units=unit)
                        self.add_output('q_dot', shape=(n,), units=f'{unit}/s')
                        self.declare_partials('q_dot', 'q', dependent=False)

                    def compute(self, inputs, outputs):
                        outputs['q_dot'][:] = (values[1] - values[0]) / 50.

                def build():
                    p = om.Problem()
                    problems.append(p)
                    tr = p.model.add_subsystem('traj', dm.Trajectory())
                    phase = tr.add_phase('phase0', dm.Phase(
                        ode_class=RateODE, transcription=dm.Radau(num_segments=4, order=3)))
                    phase.set_time_options(fix_initial=True, fix_duration=True, units='s')
                    phase.add_state('q', rate_source='q_dot', units=unit,
                                    fix_initial=True, lower=lower, upper=upper)
                    phase.add_timeseries_output('q', units=recorded)
                    p.setup()
                    phase.set_time_val(initial=0., duration=50.)
                    phase.set_state_val('q', values)
                    return p

                p1 = build()
                dm.run_problem(p1, run_driver=False, simulate=False, solution_record_file='repro.db')
                original = p1.get_val('traj.phase0.states:q', units=unit).copy()
                case = om.CaseReader(p1.get_outputs_dir() / 'repro.db').get_case('final')
                p2 = build()
                p2.final_setup()
                p2.load_case(case)
                restored = p2.get_val('traj.phase0.states:q', units=unit).copy()
                expected = original if lower is None and upper is None else np.clip(original, lower, upper)
                item.update(passed=bool(np.allclose(restored, expected, rtol=1e-12, atol=1e-11)),
                            max_abs_error=float(np.max(np.abs(restored - expected))),
                            expected_range=[float(expected.min()), float(expected.max())],
                            restored_range=[float(restored.min()), float(restored.max())])
                item['as_expected'] = item['passed'] == (True if variant == 'candidate' else baseline_pass)
            except Exception as exc:
                item.update(passed=False, as_expected=False, error=repr(exc), traceback=traceback.format_exc())
            finally:
                for p in problems:
                    p.cleanup()
                os.chdir(before)
        receipt['cases'].append(item)
        print(json.dumps(item), flush=True)
    receipt['passed'] = sum(item['passed'] for item in receipt['cases'])
    receipt['total'] = len(cases)
    receipt['expected_comparison_verified'] = all(item['as_expected'] for item in receipt['cases'])
    (OUT / f'{variant}.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt), flush=True)
    return 0 if receipt['expected_comparison_verified'] else 1


if __name__ == '__main__':
    mode = sys.argv[1]
    if mode == 'patch':
        patch()
    elif mode in ('baseline', 'candidate'):
        raise SystemExit(run(mode))
    else:
        raise SystemExit('Expected baseline, candidate, or patch')
