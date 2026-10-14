import unittest
from converged_sim.finite_source import run,finite_shape,constant_refill,biased_refill
from converged_sim.robustness_model import service_trace,run as old_run
from converged_sim.adaptive_shaper import run as ideal_run,shape


class FiniteSourceTests(unittest.TestCase):
    def test_frozen_engine_equivalence(self):
        for mode,policy in (("fifo","fifo"),("priority","strict_priority")):
            a=run(.8,3,8,8,31,mode=mode,measured=200,warmup=16)
            b=old_run(.8,3,8,8,31,policy=policy,measured=200,warmup=16)
            self.assertEqual(a["summaries"],b["summaries"])
            for x,y in zip(a["packets"],b["packets"]):
                self.assertEqual({k:v for k,v in x.items() if k!="drop_stage"},y)

    def test_large_finite_queue_matches_ideal_feedback(self):
        a=run(.95,3,8,8,31,mode="feedback",capacity=32,bias=0,lag=.5,measured=200,warmup=16)
        b=ideal_run(.95,3,8,8,31,lag=.5,measured=200,warmup=16)
        self.assertEqual(a["summaries"],b["summaries"])
        self.assertEqual(a["source_bulk_dropped"],0)

    def test_drop_does_not_consume_tokens(self):
        trace=service_trace(16.,116.,700.,2.,5,True);refill=constant_refill(trace,1.)
        releases,maximum=finite_shape([0.]*5,refill,.1,.1)
        self.assertEqual(releases[:2],[0.,.1])
        self.assertEqual(releases[2:],[None]*3)
        self.assertAlmostEqual(maximum,.1)

    def test_causal_prefix_and_bounded_source(self):
        a=service_trace(16.,116.,700.,2.,5,True);b=service_trace(16.,116.,700.,2.,5,True)
        b.rates=[r if t<10 else .9 for t,r in zip(b.starts,b.rates)]
        arrivals=[i*.02 for i in range(1000)]
        x,_=finite_shape(arrivals,biased_refill(a,.8,.5,.1),.1,2.)
        y,_=finite_shape(arrivals,biased_refill(b,.8,.5,.1),.1,2.)
        for at,u,v in zip(arrivals,x,y):
            if at<10:
                self.assertEqual(u is None,v is None)
                if u is not None and u<10: self.assertEqual(u,v)
        r=run(.95,3,8,8,31,mode="feedback",capacity=2,bias=-.1,lag=.5,measured=500,warmup=16)
        self.assertLessEqual(r["source_max_queued_work"],2.+1e-12)
        self.assertGreater(r["source_bulk_dropped"],0)
        self.assertEqual(r["summaries"]["bulk"]["dropped"],r["source_bulk_dropped"]+r["link_bulk_dropped"])
