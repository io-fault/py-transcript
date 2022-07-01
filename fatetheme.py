"""
# Source data for display layout for test fate metrics.
"""
from . import terminal
from ..context import tools

order = [
	('executing', 'work.w_executing', 8),
	('usage', 'usage.r_process', 8),
	('passed', 'work.w_executed', 8),
	('skipped', 'work.w_granted', 8),
	('failed', 'work.w_failed', 8),
]

formats = [
	('x', "executing", 'orange', tools.partial(terminal.r_count, 'executing')),
	('u', "usage", 'violet', tools.partial(terminal.r_count, 'usage')),
	('p', "passed", 'green', tools.partial(terminal.r_count, 'passed')),
	('s', "skipped", 'blue', tools.partial(terminal.r_count, 'skipped')),
	('f', "failed", 'red', tools.partial(terminal.r_count, 'failed')),
]

types = {
	'usage': 'rate_window',
}
