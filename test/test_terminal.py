"""
# Validate terminal classes and functionality.
"""
from .. import terminal as module

def test_Metrics_init(test):
	# Sanity.
	m = module.Metrics()
	test/m.window == 8

	m = module.Metrics(window=12)
	test/m.window == 12

	test/m.history == []
	test/m.current == {}
	test/m.snapshot == {}
	test/m.duration == 0

def test_Metrics_clear(test):
	m = module.Metrics()
	m.update('k', 1)
	m.commit(1)
	test/m.total('k') == 1
	test/m.duration == 1

	m.clear()
	test/m.duration == 0
	test/m.history == []
	test/m.snapshot == {}
	test/m.current == {}

def test_Metrics_commit(test):
	m = module.Metrics()
	test/len(m.history) == 0

	m.commit(0)
	test/m.duration == 0
	test/len(m.history) == 1

	m.commit(1)
	test/m.duration == 1
	test/len(m.history) == 2
	m.commit(1)
	test/m.duration == 2
	test/len(m.history) == 3

def test_Metrics_total(test):
	m = module.Metrics()
	m.update('k', 1)

	# Counted prior to commit().
	test/m.total('k') == 1
	test/m.duration == 0

	m.commit(1)
	test/m.total('k') == 1
	test/m.duration == 1

def test_Metrics_rate(test):
	m = module.Metrics()
	m.update('k', 1)
	test/ZeroDivisionError ^ (lambda: m.rate('k'))
	test/m.duration == 0

	m.commit(2)
	r = m.rate('k')
	test/int(r * 2) == 1

def test_Metrics_recent(test):
	m = module.Metrics()
	m.update('k', 1)
	test/m.recent('k') == 0 # Not committed.
	test/m.duration == 0

	m.commit(2)
	test/m.recent('k') == 1

	# Independent updates are incremental.
	m.update('k', 1)
	m.update('k', 1)
	m.commit(1)
	test/m.recent('k') == 3
	test/m.total('k') == 3

def test_Metrics_changes(test):
	m = module.Metrics()
	test/set(m.changes()) == set()

	m.update('k1', 1)
	m.update('k2', 3)
	m.update('k3', 3)
	test/set(m.changes()) == {'k1', 'k2', 'k3'}

	m.commit(1)
	test/set(m.changes()) == set()

def test_Metrics_trim(test):
	m = module.Metrics(window=4)
	m.update('k', 10)
	m.commit(2)
	m.update('k', 10)
	m.commit(2)
	m.update('k', 10)
	m.commit(2)
	test/len(m.history) == 3

	test/(m.rate('k') * 6) == 30
	m.trim()
	test/(m.rate('k') * 4) == 20
	# Length is still three because it's the edge.
	test/len(m.history) == 3

def test_Metrics_trim_exclusion(test):
	m = module.Metrics(window=4)
	m.update('k', 10)
	m.commit(2)
	m.update('k', 10)
	m.commit(2)
	m.update('k', 10)
	m.commit(2)
	m.update('k', 10)
	m.commit(2)
	test/len(m.history) == 4

	test/(m.rate('k') * 6) == 30
	m.trim()
	test/(m.rate('k') * 4) == 20
	# First entry fully exceeded window, so it was removed.
	test/len(m.history) == 3

if __name__ == '__main__':
	import sys; from ...test import engine
	engine.execute(sys.modules[__name__])