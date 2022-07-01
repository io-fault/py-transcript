"""
# Validate terminal classes and functionality.
"""
from .. import terminal as module

if __name__ == '__main__':
	import sys; from ...test import engine
	engine.execute(sys.modules[__name__])
