"""
# Source data for display layout for transfer metrics.
"""
from . import terminal
from ..context import tools

order = [
	('executing', 8),
	('received', 8),
	('transmitted', 8),
	('failed', 8),
	('completed', 8),
]

formats = [
	('x', "executing", 'orange', tools.partial(terminal.r_count, 'executing')),
	('r', "rx", 'blue', tools.partial(terminal.r_count, 'received')),
	('t', "tx", 'red', tools.partial(terminal.r_count, 'transmitted')),
	('f', "failed", 'yellow', tools.partial(terminal.r_count, 'failed')),
	('c', "completed", 'green', tools.partial(terminal.r_count, 'completed')),
]

types = {
	'received': 'rate',
	'transmitted': 'rate',
}
