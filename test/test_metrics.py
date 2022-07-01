"""
# Validate the field sets and functionality of the metrics module.
"""
from dataclasses import fields
from .. import metrics as module

def test_Work(test):
	w = module.Work()
	test/w.w_prepared == 0
	test/w.w_executed == 0
	test/w.w_granted == 0
	test/w.w_failed == 0
	test/w.empty() == True
	test/w.w_total == 0

def test_Work_add(test):
	w = module.Work()
	test/(w + module.Work(1,0,0,1)).w_total == 1

def test_Adivsory(test):
	m = module.Advisory()
	test/m.m_notices == 0
	test/m.m_warnings == 0
	test/m.m_errors == 0
	test/m.empty() == True
	test/m.m_total == 0

def test_Adivsory_add(test):
	m = module.Advisory()
	test/(m + module.Advisory(1)).m_total == 1

def test_Resource(test):
	u = module.Resource()
	test/u.r_divisions == 0
	test/u.r_time == 0
	test/u.r_memory == 0
	test/u.r_process == 0
	test/u.empty() == True

def test_Resource_add(test):
	u = module.Resource()
	test/(u + module.Resource(r_divisions=1)).r_divisions == 1
	test/(u + module.Resource(r_memory=1)).r_memory == 1
	test/(u + module.Resource(r_process=1)).r_process == 1
	test/(u + module.Resource(r_time=1)).r_time == 1

def test_Procedure_io(test):
	"""
	# - &module.Procedure.sequence
	# - &module.Procedure.structure
	"""
	p1 = module.Procedure.structure('@1!2*3')
	test/p1.msg.m_notices == 1
	test/p1.msg.m_warnings == 2
	test/p1.msg.m_errors == 3

	p2 = module.Procedure.structure('%10+20-30/5')
	test/p2.work.w_prepared == 5
	test/p2.work.w_executed == 10
	test/p2.work.w_granted == 20
	test/p2.work.w_failed == 30

	p3 = module.Procedure.structure('$1:2#3/20')
	test/p3.usage.r_divisions == 20
	test/p3.usage.r_process == 1
	test/p3.usage.r_time == 2
	test/p3.usage.r_memory == 3

	p4 = module.Procedure.structure('%10+20-30/5 @1!2*3 $1:2#3/20')
	test/(p1 + p2 + p3) == p4

	test/p4.sequence() == '%10+20-30/5 @1!2*3 $1:2#3/20'

def test_Procedure_indexing(test):
	"""
	# - &module.Procedure.__getitem__
	"""
	p = module.Procedure.structure('%10+20-30/5 @1!2*3 $1:2#3/20')
	test/p[('work', 'w_prepared')] == 5
	test/p[('msg', 'm_errors')] == 3
	test/p[('usage', 'r_divisions')] == 20
