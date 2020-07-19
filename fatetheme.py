"""
# Source data for display layout for test fate metrics.
"""
from . import terminal
from ..context import tools

order = [
	('executing', 8),
	('usage', 8),
	('passed', 8),
	('skipped', 8),
	('failed', 8),
]

formats = [
	('x', "executing", 'orange', tools.partial(terminal.r_count, 'executing')),
	('u', "usage", 'violet', tools.partial(terminal.r_count, 'usage')),
	('p', "passed", 'green', tools.partial(terminal.r_count, 'passed')),
	('s', "skipped", 'blue', tools.partial(terminal.r_count, 'skipped')),
	('f', "failed", 'red', tools.partial(terminal.r_count, 'failed')),
]
