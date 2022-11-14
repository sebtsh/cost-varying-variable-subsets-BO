from abc import ABC, abstractmethod
from scipy.stats import norm
import torch
import numpy as np

from core.utils import expectation_det, maximize_fn


class Distribution(ABC):
    def __init__(self):
        super().__init__()

    @abstractmethod
    def sample(self, n_samples):
        pass

    @abstractmethod
    def variance(self):
        pass


class TruncNormDist(Distribution):
    def __init__(self, loc, scale, a, b):
        super().__init__()
        self.loc = loc
        self.scale = scale
        self.a = a
        self.b = b

    def sample(self, n_samples):
        return torch.tensor(
            truncnorm_samples(
                loc=self.loc, scale=self.scale, a=self.a, b=self.b, n_samples=n_samples
            ),
            dtype=torch.double,
        )

    def variance(self):
        return truncnorm_variance(loc=self.loc, scale=self.scale, a=self.a, b=self.b)


class UniformDist(Distribution):
    def __init__(self, a, b):
        super().__init__()
        self.a = a
        self.b = b

    def sample(self, n_samples):
        return uniform_samples_1d(a=self.a, b=self.b, n_samples=n_samples)

    def variance(self):
        return (1 / 12) * ((self.b - self.a) ** 2)


def truncnorm_transform(U, loc, scale, a, b):
    """
    :param U: samples from Uniform(0, 1).
    """
    alpha = (a - loc) / scale
    beta = (b - loc) / scale
    return (
        norm.ppf(norm.cdf(alpha) + U * (norm.cdf(beta) - norm.cdf(alpha))) * scale + loc
    )


def truncnorm_samples(loc, scale, a, b, n_samples):
    """
    Samples from a normal distribution with loc and scale but truncated to the range [a, b].
    """
    U = uniform_samples_1d(a=0.0, b=1.0, n_samples=n_samples)
    return truncnorm_transform(U=U, loc=loc, scale=scale, a=a, b=b)


def truncnorm_variance(loc, scale, a, b):
    alpha = (a - loc) / scale
    beta = (b - loc) / scale
    Z = norm.cdf(beta) - norm.cdf(alpha)

    A = (alpha * norm.pdf(alpha) - beta * norm.pdf(beta)) / Z
    B = ((norm.pdf(alpha) - norm.pdf(beta)) / Z) ** 2

    return (scale**2) * (1 + A - B)


def get_truncnorm_scale(desired_var, loc, a, b):
    low = 0.001
    high = 100
    if truncnorm_variance(loc, low, a, b) > desired_var:
        raise Exception("low is too high!")

    if truncnorm_variance(loc, high, a, b) < desired_var:
        raise Exception("high is too low!")

    mid = (low + high) / 2
    curr_var = truncnorm_variance(loc, mid, a, b)
    while not np.allclose(curr_var, desired_var):
        mid = (low + high) / 2
        curr_var = truncnorm_variance(loc, mid, a, b)
        if curr_var > desired_var:
            high = mid
        elif curr_var <= desired_var:
            low = mid

    return mid


def uniform_samples_1d(a, b, n_samples):
    return torch.rand(size=(n_samples,), dtype=torch.double) * (b - a) + a


def get_dists_and_samples(dims, variance):
    n_samples = 2**13

    loc = 0.5
    a = 0.0
    b = 1.0

    scale = get_truncnorm_scale(desired_var=variance, loc=loc, a=a, b=b)

    all_dists = [TruncNormDist(loc=loc, scale=scale, a=a, b=b) for _ in range(dims)]

    all_dists_samples = torch.cat(
        [dist.sample(n_samples)[:, None] for dist in all_dists], dim=-1
    )

    return all_dists, all_dists_samples


def get_opt_queries_and_vals(f, control_sets, random_sets, all_dists_samples, bounds):
    m = len(control_sets)
    dims = bounds.shape[-1]

    opt_queries = []
    opt_vals = []

    for i in range(m):
        control_set_idxs = control_sets[i]

        if len(control_sets) == dims:
            # if full control set, avoid expectation calculations
            opt_query, opt_val = maximize_fn(f=f, n_warmup=10000, bounds=bounds)
        else:
            random_set_idxs = random_sets[i]
            random_dists_samples = all_dists_samples[
                :, random_set_idxs
            ]  # (n_samples, d_r)

            cat_idxs = np.concatenate([control_set_idxs, random_set_idxs])
            order_idxs = np.array(
                [np.where(cat_idxs == j)[0][0] for j in np.arange(len(cat_idxs))]
            )

            opt_query, opt_val = maximize_fn(
                f=lambda x: expectation_det(
                    f=f,
                    x_control=x,
                    random_dists_samples=random_dists_samples,
                    order_idxs=order_idxs,
                ),
                bounds=bounds[:, control_set_idxs],
            )

        opt_queries.append(opt_query)
        opt_vals.append(opt_val)

    return opt_queries, opt_vals