from abc import ABC, abstractmethod
import numpy as np
import torch

from core.utils import powerset


def get_eps_schedule(
    id, costs, control_sets, random_sets, variances, lengthscales, budget
):
    if id == 0:
        return AdaSchedule(
            costs=costs,
            control_sets=control_sets,
            random_sets=random_sets,
            variances=variances,
            lengthscales=lengthscales,
        )
    if id == 1:
        return LinearSchedule(start_eps=2.0, cutoff_iter=int(budget / costs[-1]))
    if id == 2:
        return LinearSchedule(start_eps=2.0, cutoff_iter=200)
    if id == 3:
        return LinearSchedule(start_eps=2.0, cutoff_iter=400)
    if id == 4:
        return AdaLinSchedule(
            start_eps=2.0,
            cutoff_mult=1.0,
            var_aware=False,
            costs=costs,
            random_sets=random_sets,
            variances=variances,
        )
    if id == 5:
        return AdaLinSchedule(
            start_eps=2.0,
            cutoff_mult=1.0,
            var_aware=True,
            costs=costs,
            random_sets=random_sets,
            variances=variances,
        )
    else:
        raise NotImplementedError


class EpsilonSchedule(ABC):
    def __init__(self):
        super().__init__()
        self.last_eps = None

    @abstractmethod
    def next(self, opt_vals):
        pass


class AdaLinSchedule(EpsilonSchedule):
    def __init__(
        self, start_eps, cutoff_mult, var_aware, costs, random_sets, variances
    ):
        super().__init__()
        self.start_eps = start_eps

        # construct sum of variances
        m = len(random_sets)
        sum_of_variances = np.zeros(m - 1)
        for i in range(m - 1):
            sum_of_variances[i] = np.sum(variances[random_sets[i]] / (1 / 12))

        if var_aware:
            cutoff_iter = np.sum(costs[-1] / costs[:-1] * sum_of_variances)
        else:
            cutoff_iter = np.sum(costs[-1] / costs[:-1])

        self.cutoff_iter = int(cutoff_mult * cutoff_iter)
        self.t = 0

    def next(self, opt_vals):
        eps = self.start_eps * np.maximum(1 - self.t / self.cutoff_iter, 0.0)
        self.last_eps = eps
        return eps

    def update(self, prev_control_idx):
        self.t += 1


class AdaSchedule(EpsilonSchedule):
    def __init__(self, costs, control_sets, random_sets, variances, lengthscales):
        """

        :param costs: array of shape (m, ) of costs.
        :param control_sets:list of arrays of variables in each control set.
        :param random_sets: list of arrays of variables in each random set.
        :param variances: array of variances of each variable.
        :param lengthscales: array of lengthscales of each variable.
        """
        super().__init__()

        m = len(random_sets)
        self.m = m
        assert len(random_sets[-1]) == 0  # implicit assumption that
        # the last control set is the full control set
        self.n_plays = np.zeros(m)
        all_var_ls_ratios = variances / lengthscales

        # Generate target no. of plays
        target_plays = np.zeros(m)
        for i in range(m - 1):
            # Check condition 1
            zero_plays = False
            for j in range(m):
                if j == i:
                    continue
                else:
                    is_subset = len(np.setdiff1d(control_sets[i], control_sets[j])) == 0
                    if is_subset and costs[i] >= costs[j]:
                        zero_plays = True
            if zero_plays:
                continue
            else:
                var_ls_ratios = all_var_ls_ratios[random_sets[i]]
                target_plays[i] = int((costs[-1] / costs[i]) * np.sum(var_ls_ratios))
        self.target_plays = target_plays

    def next(self, opt_vals):
        eps = 0.0
        for i in range(self.m - 1):
            required_eps = opt_vals[-1] - opt_vals[i] + 1e-04
            eps_valid = True
            for j in range(i):
                if opt_vals[j] + required_eps >= opt_vals[-1]:
                    # then i would not be played with required_eps
                    eps_valid = False
                    break
            if self.n_plays[i] < self.target_plays[i] and eps_valid:
                eps = required_eps
                break
        if isinstance(eps, torch.Tensor):
            eps = eps.item()
        self.last_eps = eps
        return eps

    def update(self, prev_control_idx):
        if prev_control_idx is not None:
            self.n_plays[prev_control_idx] += 1


class LinearSchedule(EpsilonSchedule):
    def __init__(self, start_eps, cutoff_iter):
        super().__init__()
        self.start_eps = start_eps
        self.cutoff_iter = cutoff_iter
        self.t = 0

    def next(self, opt_vals):
        eps = self.start_eps * np.maximum(1 - self.t / self.cutoff_iter, 0.0)
        self.last_eps = eps
        return eps

    def update(self, prev_control_idx):
        self.t += 1


def get_control_sets(dims, control_id):
    if dims == 3:
        if control_id == 0:
            inter = powerset(np.arange(3))
        else:
            raise NotImplementedError
    elif dims == 5:
        if control_id == 0:
            inter = [
                (0, 1),
                (2, 3),
                (3, 4),
                (0, 1, 2),
                (1, 2, 3),
                (2, 3, 4),
                (0, 1, 2, 3, 4),
            ]
        else:
            raise NotImplementedError
    elif dims == 6:
        if control_id == 0:
            inter = [
                (0, 1),
                (2, 3),
                (4, 5),
                (0, 1, 2, 3),
                (1, 2, 3, 4),
                (2, 3, 4, 5),
                (0, 1, 2, 3, 4, 5),
            ]
        else:
            raise NotImplementedError
    else:
        raise NotImplementedError

    control_sets = [np.array(tup) for tup in inter]
    return control_sets


def get_costs(cost_id):
    if cost_id == 0:
        costs = np.array([0.01, 0.01, 0.01, 0.1, 0.1, 0.1, 1.0])
    elif cost_id == 1:
        costs = np.array([0.1, 0.1, 0.1, 0.2, 0.2, 0.2, 1.0])
    elif cost_id == 2:
        costs = np.array([0.6, 0.6, 0.6, 0.8, 0.8, 0.8, 1.0])
    else:
        raise NotImplementedError

    return costs


def get_random_sets(dims, control_sets):
    random_sets = []
    for control_set in control_sets:
        random_sets.append(np.setdiff1d(np.arange(dims), control_set))

    return random_sets


def get_control_sets_and_costs(dims, control_sets_id, costs_id):
    control_sets = get_control_sets(dims=dims, control_id=control_sets_id)

    random_sets = get_random_sets(dims=dims, control_sets=control_sets)

    for i in range(len(control_sets)):
        assert np.allclose(
            np.sort(np.concatenate([control_sets[i], random_sets[i]])), np.arange(dims)
        )

    costs = get_costs(cost_id=costs_id)

    assert len(costs) == len(control_sets)

    return control_sets, random_sets, costs
