"""Local sufficient condition, not independently reviewed or claimed novel."""
import math


def condition(rho,error_upper,lag,bucket=.1,critical_burst=.05,cmin=.7,cmax=1.3,deadline=1.):
    values=(rho,error_upper,lag,bucket,critical_burst,cmin,cmax,deadline)
    if not all(math.isfinite(v) for v in values) or not 0<rho<=1 or error_upper<0 or lag<0 or bucket<0 or critical_burst<0 or not 0<cmin<=cmax or deadline<=0:
        raise ValueError("invalid sufficient-condition inputs")
    slack=(1-rho)*cmin-rho*error_upper
    work=bucket+critical_burst+(cmax-cmin)*rho*lag
    return dict(headroom_slack=slack,error_upper_budget=cmin*(1-rho)/rho,
        maximum_load_from_error=cmin/(cmin+error_upper),backlog_bound=work,
        delay_bound=work/cmin if slack>=-1e-12 else None,
        sufficient=slack>=-1e-12 and work<cmin*deadline)
