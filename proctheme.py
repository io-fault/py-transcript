"""
# Source data for display layout for processing metrics.
"""
from . import terminal
from ..context import tools

order = [
	('executing', 8),
	('usage', 8),
	('cached', 8),
	('failed', 8),
	('processed', 8),
]

formats = [
	('x', "executing", 'orange', tools.partial(terminal.r_count, 'executing')),
	('u', "usage", 'violet', tools.partial(terminal.r_count, 'usage')),
	('c', "cached", 'blue', tools.partial(terminal.r_count, 'cached')),
	('f', "failed", 'red', tools.partial(terminal.r_count, 'failed')),
	('p', "processed", 'green', tools.partial(terminal.r_count, 'processed')),
]

types = {
	'usage': 'rate',
}
