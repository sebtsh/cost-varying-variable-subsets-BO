from gpytorch.likelihoods.gaussian_likelihood import GaussianLikelihood
from gpytorch.kernels import ScaleKernel, RBFKernel
import matplotlib
import numpy as np
from pathlib import Path
import pickle
from sacred import Experiment
from sacred.observers import FileStorageObserver
import torch

from core.dists import get_dists_and_samples, get_marginal_var
from core.objectives import get_objective
from core.optimization import bo_loop
from core.psq import get_control_sets_and_costs, get_eps_schedule
from core.regret import get_regret, plot_regret
from core.utils import log, uniform_samples, load_most_recent_state


matplotlib.use("Agg")
ex = Experiment("CS-PSQ-BO")
ex.observers.append(FileStorageObserver("./runs"))


@ex.named_config
def gpsample():
    obj_name = "gpsample"
    acq_name = "ucb-cs"
    dims = 3
    control_sets_id = 0
    costs_id = 0
    eps_schedule_id = 0
    budget = 100
    var_id = 0
    noise_std = 0.01
    init_lengthscale = 0.1
    n_init_points = 5
    seed = 0
    load_state = False


@ex.named_config
def hartmann():
    obj_name = "hartmann"
    acq_name = "ucb"
    dims = 6
    control_sets_id = 0
    costs_id = 0
    eps_schedule_id = 0
    budget = 500
    var_id = 0
    noise_std = 0.01
    init_lengthscale = 0.2
    n_init_points = 5
    seed = 0
    load_state = False


@ex.named_config
def plant():
    obj_name = "plant"
    acq_name = "ucb"
    dims = 5
    control_sets_id = 0
    costs_id = 0
    eps_schedule_id = 0
    budget = 500
    var_id = 0
    noise_std = 0.01
    init_lengthscale = 0.2
    n_init_points = 5
    seed = 0
    load_state = False


@ex.automain
def main(
    obj_name,
    acq_name,
    dims,
    control_sets_id,
    costs_id,
    eps_schedule_id,
    var_id,
    noise_std,
    init_lengthscale,
    n_init_points,
    budget,
    seed,
    load_state,
):
    args = dict(locals().items())
    log(f"Running with parameters {args}")
    run_id = ex.current_run._id
    torch.manual_seed(seed)

    # Directory for saving results
    base_dir = "results/" + obj_name + "/"
    pickles_save_dir = base_dir + "pickles/"
    figures_save_dir = base_dir + "figures/"
    inter_save_dir = base_dir + "inter/"
    Path(pickles_save_dir).mkdir(parents=True, exist_ok=True)
    Path(figures_save_dir).mkdir(parents=True, exist_ok=True)
    Path(inter_save_dir).mkdir(parents=True, exist_ok=True)
    filename = (
        f"{obj_name}_{acq_name}_es{eps_schedule_id}_con{control_sets_id}_c{costs_id}"
        f"_var{var_id}_C{budget}_seed{seed}"
    )
    filename = filename.replace(".", ",")

    # Objective function
    if obj_name == "gpsample":  # If sampling from GP, we need to define kernel first
        kernel = ScaleKernel(RBFKernel(ard_num_dims=dims))
        kernel.outputscale = 1.0
        kernel.base_kernel.lengthscale = init_lengthscale
    else:
        kernel = None

    obj_func, noisy_obj_func, opt_val_det, bounds = get_objective(
        objective_name=obj_name,
        noise_std=noise_std,
        is_input_transform=True,
        kernel=kernel,
        dims=dims,
    )

    # Initialize state
    if load_state:
        raise NotImplementedError
        # init_X, init_y, state_dict, max_iter = load_most_recent_state(
        #     inter_save_dir=inter_save_dir, filename=filename
        # )
        # start_iter = max_iter + 1
        # if max_iter is None:  # if max_iter is None, no save states found
        #     load_state = False
    else:
        log("Starting new run from iter 0")
        start_iter = 0
        state_dict = None
        # Initial data
        init_X = uniform_samples(bounds=bounds, n_samples=n_init_points)
        init_y = noisy_obj_func(init_X)

    # GP parameters
    if obj_name != "gpsample":
        dims = bounds.shape[-1]
        kernel = ScaleKernel(RBFKernel(ard_num_dims=dims))
        kernel.outputscale = 1.0
        kernel.base_kernel.lengthscale = init_lengthscale

    likelihood = GaussianLikelihood()
    likelihood.noise = noise_std**2

    # Control/random sets and costs
    control_sets, random_sets, costs = get_control_sets_and_costs(
        dims=dims, control_sets_id=control_sets_id, costs_id=costs_id
    )
    marginal_var = get_marginal_var(var_id=var_id)
    all_dists, all_dists_samples = get_dists_and_samples(
        dims=dims, variance=marginal_var
    )
    variances = marginal_var * np.ones(dims, dtype=np.double)
    lengthscales = init_lengthscale * np.ones(dims, dtype=np.double)
    eps_schedule = get_eps_schedule(
        id=eps_schedule_id,
        costs=costs,
        control_sets=control_sets,
        random_sets=random_sets,
        variances=variances,
        lengthscales=lengthscales,
        budget=budget,
    )

    # Optimization loop
    final_X, final_y, control_set_idxs, control_queries, T, all_eps = bo_loop(
        train_X=init_X,
        train_y=init_y,
        likelihood=likelihood,
        kernel=kernel,
        noisy_obj_func=noisy_obj_func,
        start_iter=start_iter,
        budget=budget,
        acq_name=acq_name,
        bounds=bounds,
        all_dists=all_dists,
        control_sets=control_sets,
        random_sets=random_sets,
        all_dists_samples=all_dists_samples,
        costs=costs,
        eps_schedule=eps_schedule,
        filename=filename,
        inter_save_dir=inter_save_dir,
    )
    # Regret
    log("Calculating regret")
    simple_regret, cumu_regret, cs_cumu_regret, cost_per_iter = get_regret(
        control_set_idxs=control_set_idxs,
        control_queries=control_queries,
        obj_func=obj_func,
        control_sets=control_sets,
        random_sets=random_sets,
        all_dists_samples=all_dists_samples,
        bounds=bounds,
        costs=costs,
    )

    plot_regret(
        regret=cumu_regret,
        cost_per_iter=cost_per_iter,
        x_axis="T",
        num_iters=T,
        save=True,
        save_dir=figures_save_dir,
        filename=filename + "_T",
    )

    plot_regret(
        regret=cs_cumu_regret,
        cost_per_iter=cost_per_iter,
        x_axis="C",
        num_iters=T,
        save=True,
        save_dir=figures_save_dir,
        filename=filename + "_C",
    )

    plot_regret(
        regret=simple_regret,
        cost_per_iter=cost_per_iter,
        x_axis="C",
        num_iters=T,
        save=True,
        save_dir=figures_save_dir,
        filename=filename + "_Csimple",
    )

    # Save results
    pickle.dump(
        (
            final_X,
            final_y,
            control_set_idxs,
            control_queries,
            all_dists_samples,
            simple_regret,
            cumu_regret,
            cs_cumu_regret,
            cost_per_iter,
            T,
            args,
        ),
        open(pickles_save_dir + f"{filename}.p", "wb"),
    )

    print("cumu_regret:")
    print(cumu_regret)
    print("control_set_idxs:")
    print(control_set_idxs)
    print("control_queries:")
    print(control_queries)
    print("final X:")
    print(final_X)
    print("final y:")
    print(final_y)
    print("all_eps:")
    print(all_eps)

    log(f"Completed run {run_id} with parameters {args}")
