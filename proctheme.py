"""
# Source data for display layout for processing metrics.
"""
from . import terminal
from ..context import tools

order = [
	('executing', 'work.w_executing', 8),
	('usage', 'usage.r_process', 8),
	('cached', 'work.w_granted', 8),
	('failed', 'work.w_failed', 8),
	('processed', 'work.w_executed', 8),
]

formats = [
	('x', "executing", 'orange', tools.partial(terminal.r_count, 'executing')),
	('u', "usage", 'violet', tools.partial(terminal.r_count, 'usage')),
	('c', "cached", 'blue', tools.partial(terminal.r_count, 'cached')),
	('f', "failed", 'red', tools.partial(terminal.r_count, 'failed')),
	('p', "processed", 'green', tools.partial(terminal.r_count, 'processed')),
]

types = {
	'usage': 'rate_window',
}
