import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.distributions import Categorical
import gymnasium as gym
import logging
import time
from gymnasium import spaces
from tqdm import tqdm
from . import utilizations
from .dose_pre.inference import DoseInferenceDeadlineExceeded
from .reward_metrics import normalized_oar_damage, plan_objective
from .rl_status import new_rl_status, set_outcome, update_best
from .planning_preview import safe_preview
try:
    from . import _reward_core
except ImportError:
    _reward_core = None

logger = logging.getLogger(__name__)

# Real state features for the low-level policy: relative coverage, OAR burden,
# budget usage, and remaining free candidates.  The high-level decision is a
# one-step bandit over a fixed action set (every episode starts from an empty
# plan), so it keeps a one-dimensional state and learns action preferences.
POLICY_STATE_DIM = 4


def _dvh_oar_jit_fallback(dose_flat, target_idx, non_target_idx,
                          in_lowest_dose, out_highest_dose, count_out=False):
    """Pure numpy fallback for _reward_core._dvh_oar_jit when JIT extension unavailable.

    Returns (dvh_rate, out_damage):
      dvh_rate: fraction of target voxels with dose >= in_lowest_dose
      out_damage: if count_out, penalty for non-target voxels exceeding out_highest_dose;
                  else 0.0
    """
    target_doses = dose_flat[target_idx]
    n_target = len(target_doses)
    if n_target == 0:
        return 0.0, 0.0
    covered = np.count_nonzero(target_doses >= in_lowest_dose)
    dvh_rate = float(covered) / float(n_target)

    if not count_out:
        return dvh_rate, 0.0

    non_target_doses = dose_flat[non_target_idx]
    exceed_count = np.count_nonzero(non_target_doses > out_highest_dose)
    # Normalize overdose burden to the target volume and bound it. This makes
    # reward monotonic: more OAR overdose can never increase the reward.
    out_damage = normalized_oar_damage(exceed_count, n_target)
    return dvh_rate, out_damage
from typing import Tuple
try:
    import slicer
except ImportError:
    from . import slicer_mock as slicer



# ==========================================================
# 1.  Reward Calculator (with seed cache - kept)
# ==========================================================
# class SeedPlacementReward:
#     """
#     Reward function for seed placement in brachytherapy planning.
#     """
#     def __init__(self,
#                  dose_cal_model,
#                  dose_image,
#                  radiation_volume,
#                  target_value,
#                  in_lowest_dose,
#                  out_highest_dose,
#                  infer_img_size,
#                  seed_info,
#                  image_normalize_min,
#                  target_valueimage_normalize_max,   # REVIEW: typo left for compatibility
#                  image_normalize_scale,
#                  DVH_rate):
#         self.dose_cal_model = dose_cal_model
#         self.dose_image = dose_image
#         self.radiation_volume = radiation_volume
#         self.target_value = target_value
#         self.in_lowest_dose = in_lowest_dose
#         self.out_highest_dose = out_highest_dose
#         self.infer_img_size = infer_img_size
#         self.seed_info = seed_info
#         self.image_normalize_min = image_normalize_min
#         self.target_valueimage_normalize_max = target_valueimage_normalize_max
#         self.image_normalize_scale = image_normalize_scale

#         # Precompute masks and sizes once
#         self.mask_volume = (self.radiation_volume == self.target_value).astype(float)
#         self.total_v = np.prod(self.radiation_volume.shape)
#         self.target_v = np.sum(self.mask_volume)
#         self.DVH_rate = DVH_rate
#         self.seed_cache = {}
#         self.target_idx = np.where(self.mask_volume > 0)
#         self.non_target_idx = np.where(self.mask_volume == 0)

#     # ------------------------------------------------------
#     def forward(self, traj, cur_radiation, direction, seed_point, protect_OAR = True):
#         """
#         Compute reward for placing a seed along the given trajectory.
#         Returns:
#             reward (float), updated dose (np.ndarray), new DVH rate (float), seed_radiation (np.ndarray)
#         """
#         cur_seed_radiation = None
#         key = tuple(np.round(seed_point).astype(int))

#         # Try seed cache
#         cur_seed_radiation = self.seed_cache.get(key, None)

#         # If not cached, try matching against trajectory cached seeds (keeps original behavior)
#         if cur_seed_radiation is None:
#             for cached_seed, cached_dose in zip(traj[2], traj[3]):
#                 # cached_seed[0] assumed to be position vector like seed_point
#                 if np.linalg.norm(np.array(cached_seed[0]).reshape(-1) - seed_point) < 1e-3:
#                     cur_seed_radiation = cached_dose
#                     break

#         # If still None, compute using provided function
#         if cur_seed_radiation is None:
#             cur_seed_radiation = utilizations.single_seed_dose_calculation_dl(
#                 np.array(seed_point).astype(int).reshape(-1),
#                 direction,
#                 self.dose_image,
#                 self.dose_cal_model,
#                 self.infer_img_size,
#                 self.seed_info,
#                 self.image_normalize_min,
#                 self.target_valueimage_normalize_max,
#                 self.image_normalize_scale
#             )
#             self.seed_cache[key] = cur_seed_radiation

#         # accumulate radiation (non in-place for safety)
#         cur_radiation = cur_radiation + cur_seed_radiation

#         # Use precomputed idx for speed
#         target_voxels = cur_radiation[self.target_idx]
#         # compute DVH rate
#         cur_DVH_rate = np.mean(target_voxels > self.in_lowest_dose)
#         if not protect_OAR:
#             reward = cur_DVH_rate
#         else:
#             non_target_voxels = cur_radiation[self.non_target_idx]
#             out_damage = np.count_nonzero(non_target_voxels > self.out_highest_dose) / max(1.0, self.target_v)
#             # reward formula preserved
#             reward = min(cur_DVH_rate, self.DVH_rate) + ((cur_DVH_rate - self.DVH_rate) >= 0) * ((1 - out_damage))
#         return reward, cur_radiation, cur_DVH_rate, cur_seed_radiation



# ----------  Reward class  ----------
class SeedPlacementReward:
    """
    Incremental reward for seed placement in brachytherapy.
    Uses CNN-based single-seed dose + position cache + JIT metrics.
    """
    def __init__(self,
                 dose_cal_model: nn.Module,
                 dose_image: np.ndarray,
                 radiation_volume: np.ndarray,
                 target_value: float,
                 in_lowest_dose: float,
                 out_highest_dose: float,
                 infer_img_size: tuple,
                 seed_info: dict,
                 image_normalize_min: float,
                 target_valueimage_normalize_max: float,  # typo kept
                 image_normalize_scale: float,
                 DVH_rate: float,
                 deadline=None,
                 ) -> None:

        self.dose_cal_model = dose_cal_model
        self.dose_image = dose_image
        self.radiation_volume = radiation_volume
        self.target_value = target_value
        self.in_lowest_dose = in_lowest_dose
        self.out_highest_dose = out_highest_dose
        self.infer_img_size = infer_img_size
        self.seed_info = seed_info
        self.image_normalize_min = image_normalize_min
        self.target_valueimage_normalize_max = target_valueimage_normalize_max
        self.image_normalize_scale = image_normalize_scale
        self.DVH_rate = DVH_rate
        self.deadline = deadline
        self.last_coverage = 0.0
        self.last_out_damage = 0.0

        # one-time masks
        self.mask_volume = (radiation_volume == target_value).astype(float)
        self.non_target_mask  = (radiation_volume != target_value).astype(float)
        self.seed_cache: dict[tuple, np.ndarray] = {}
        # Runtime telemetry distinguishes a bounded but expensive RL run from
        # an actual control-flow stall. It is intentionally aggregate-only so
        # no patient geometry is emitted to logs.
        self.cache_hits = 0
        self.cache_misses = 0
        self.model_inference_seconds = 0.0

        # flat indices for JIT speed
        self.target_idx = np.where(self.mask_volume.ravel() > 0)[0].astype(np.int32)
        self.target_v = self.target_idx.size
        self.non_target_idx = np.where(self.mask_volume.ravel() == 0)[0].astype(np.int32)
        self.non_target_v = self.non_target_idx.size
        
        

    # ------------------------------------------------------------------
    @staticmethod
    def cache_key_for(seed_point, direction):
        """Cache identity of one seed: voxel position AND its direction.

        A single-seed dose map depends on the seed axis, so a position-only key
        could hand a crossing needle the wrong (direction-specific) map.
        """
        point = np.asarray(seed_point, dtype=np.float64).reshape(-1)
        axis = np.asarray(direction, dtype=np.float64).reshape(-1)
        norm = float(np.linalg.norm(axis))
        if norm > 1e-12:
            axis = axis / norm
        return (tuple(np.round(point, 3).tolist()), tuple(np.round(axis, 6).tolist()))

    def _metrics(self, dose_flat):
        """Return (coverage, out_damage) for one accumulated dose volume."""
        _fn = _reward_core._dvh_oar_jit if _reward_core is not None else _dvh_oar_jit_fallback
        return _fn(
            dose_flat,
            np.ascontiguousarray(self.target_idx, dtype=np.int32),
            np.ascontiguousarray(self.non_target_idx, dtype=np.int32),
            float(self.in_lowest_dose),
            float(self.out_highest_dose),
            count_out=True,
        )

    def _lookup_seed_dose(self, traj, seed_point, direction, key):
        cached = self.seed_cache.get(key, None)
        if cached is not None:
            self.cache_hits += 1
            return cached
        point_arr = np.asarray(seed_point, dtype=np.float64).reshape(-1)
        axis_arr = np.asarray(direction, dtype=np.float64).reshape(-1)
        axis_norm = float(np.linalg.norm(axis_arr))
        if axis_norm > 1e-12:
            axis_arr = axis_arr / axis_norm
        for cached_seed, cached_dose in zip(traj[2], traj[3]):
            stored_point = np.asarray(cached_seed[0], dtype=np.float64).reshape(-1)
            if stored_point.size != 3 or np.linalg.norm(stored_point - point_arr) >= 1e-3:
                continue
            stored_axis = np.asarray(cached_seed[1], dtype=np.float64).reshape(-1)
            stored_norm = float(np.linalg.norm(stored_axis))
            if stored_norm > 1e-12:
                stored_axis = stored_axis / stored_norm
            if float(np.dot(stored_axis, axis_arr)) < 0.999:
                continue
            # Dose maps are treated as immutable; share the reference instead
            # of duplicating full planning-grid volumes in the cache.
            self.seed_cache[key] = cached_dose
            self.cache_hits += 1
            return cached_dose
        return None

    def import_trajectory_dose_maps(self, traj_elem):
        """Reuse dense-evaluation dose maps instead of re-running the model.

        ``traj_elem`` is the hierarchical inner element
        ``[idx, traj, seeds, dose_maps, acc_radiation]``.  The dense stage
        already ran DoseUNet for every stored seed, so importing those maps
        turns the later group prefetch into pure cache hits.  Dose maps are
        immutable; the reference is shared instead of copied.
        """
        if not isinstance(traj_elem, (list, tuple)) or len(traj_elem) < 4:
            return 0
        seeds = traj_elem[2] or []
        maps = traj_elem[3] or []
        imported = 0
        for seed, dose in zip(seeds, maps):
            if dose is None:
                continue
            try:
                key = self.cache_key_for(seed[0], seed[1])
            except Exception:
                continue
            if key not in self.seed_cache:
                self.seed_cache[key] = dose
                imported += 1
        return imported

    def prefetch_positions(self, candidates):
        """Batch-fill the seed-dose cache for one group's candidate positions.

        ``candidates`` is an iterable of ``(seed_point, direction)`` in voxel
        coordinates.  One batched DoseUNet call replaces the per-step single
        forward passes the episode loop used to make.
        """
        pending = []
        for seed_point, direction in candidates:
            key = self.cache_key_for(seed_point, direction)
            if key in self.seed_cache:
                self.cache_hits += 1
                continue
            pending.append((key, seed_point, direction))
        if not pending:
            return 0
        self.cache_misses += len(pending)
        inference_started = time.perf_counter()
        dose_maps = utilizations.batch_seed_dose_calculation_dl(
            [(np.asarray(point).reshape(-1), np.asarray(axis).reshape(-1))
             for _, point, axis in pending],
            self.dose_image,
            self.dose_cal_model,
            self.infer_img_size,
            self.seed_info,
            self.image_normalize_min,
            self.target_valueimage_normalize_max,
            self.image_normalize_scale,
            deadline=self.deadline,
        )
        self.model_inference_seconds += time.perf_counter() - inference_started
        for (key, _, _), dose_map in zip(pending, dose_maps):
            self.seed_cache[key] = dose_map
        return len(pending)

    # ------------------------------------------------------------------
    def forward(self,
                traj: list,
                cur_radiation: np.ndarray,
                direction: np.ndarray,
                seed_point: np.ndarray,
                protect_OAR: bool = True,
                seed_count: int = 1,
                needle_count: int = 1,
                is_new_needle: bool = True):
        """
        Compute the marginal objective gain of placing one seed.

        Returns: reward, updated_dose, DVH_rate, seed_dose_map.

        ``reward`` is ``J(plan + seed) - J(plan)`` with the same
        :func:`plans.reward_metrics.plan_objective` used for final selection,
        so the discounted return telescopes to the plan objective and the
        training signal can never prefer more seeds than the selection signal.
        A failed dose prediction returns ``(0.0, dose, previous coverage,
        None)``: the caller must not fabricate a zero-dose seed in the plan.
        """
        try:
            key = self.cache_key_for(seed_point, direction)
            cur_seed_radiation = self._lookup_seed_dose(traj, seed_point, direction, key)

            if cur_seed_radiation is None:
                self.cache_misses += 1
                inference_started = time.perf_counter()
                cur_seed_radiation = utilizations.single_seed_dose_calculation_dl(
                    np.asarray(seed_point).astype(int).reshape(-1),
                    direction,
                    self.dose_image,
                    self.dose_cal_model,
                    self.infer_img_size,
                    self.seed_info,
                    self.image_normalize_min,
                    self.target_valueimage_normalize_max,
                    self.image_normalize_scale,
                    deadline=self.deadline,
                )
                self.model_inference_seconds += time.perf_counter() - inference_started
                self.seed_cache[key] = cur_seed_radiation

            if cur_radiation.dtype != cur_seed_radiation.dtype:
                cur_radiation = cur_radiation.astype(cur_seed_radiation.dtype)

            previous_flat = np.ascontiguousarray(cur_radiation.ravel(), dtype=np.float64)
            old_coverage, old_damage = self._metrics(previous_flat)

            np.add(cur_radiation, cur_seed_radiation, out=cur_radiation)

            dose_flat = np.ascontiguousarray(cur_radiation.ravel(), dtype=np.float64)
            cur_DVH_rate, out_damage = self._metrics(dose_flat)

            old_oar = old_damage if protect_OAR else 0.0
            new_oar = out_damage if protect_OAR else 0.0
            prev_needles = int(needle_count) - (1 if is_new_needle else 0)
            old_objective = plan_objective(
                old_coverage, old_oar,
                seed_count=max(0, int(seed_count) - 1),
                needle_count=max(0, prev_needles),
                target_coverage=self.DVH_rate,
            )
            new_objective = plan_objective(
                cur_DVH_rate, new_oar,
                seed_count=int(seed_count),
                needle_count=int(needle_count),
                target_coverage=self.DVH_rate,
            )
            reward = float(new_objective - old_objective)
            self.last_coverage = float(cur_DVH_rate)
            self.last_out_damage = float(out_damage)
            return reward, cur_radiation, cur_DVH_rate, cur_seed_radiation
        except DoseInferenceDeadlineExceeded:
            # The caller owns the episode boundary and will return its best
            # valid plan. Do not convert an expired budget into fake zero dose.
            raise
        except Exception as e:
            logger.exception("Seed-placement reward calculation failed: %s", e)
            # Never fabricate a zero-dose map: a failed prediction must leave
            # the accumulated dose untouched and return no seed map at all.
            previous_flat = np.ascontiguousarray(cur_radiation.ravel(), dtype=np.float64)
            old_coverage, _ = self._metrics(previous_flat)
            return 0.0, cur_radiation, old_coverage, None

    def evaluate_marginal(self, cur_radiation, seed_dose_map,
                          seed_count=1, needle_count=1, is_new_needle=True,
                          protect_OAR: bool = True):
        """Return the objective gain of adding one seed WITHOUT committing it.

        Used by the deterministic greedy warm start to rank candidates.
        """
        current = np.ascontiguousarray(cur_radiation, dtype=np.float32)
        addition = np.ascontiguousarray(seed_dose_map, dtype=np.float32)
        old_coverage, old_damage = self._metrics(
            np.ascontiguousarray(current.ravel(), dtype=np.float64))
        trial = current + addition
        new_coverage, new_damage = self._metrics(
            np.ascontiguousarray(trial.ravel(), dtype=np.float64))
        old_oar = old_damage if protect_OAR else 0.0
        new_oar = new_damage if protect_OAR else 0.0
        prev_needles = int(needle_count) - (1 if is_new_needle else 0)
        old_objective = plan_objective(
            old_coverage, old_oar,
            seed_count=max(0, int(seed_count) - 1),
            needle_count=max(0, prev_needles),
            target_coverage=self.DVH_rate,
        )
        new_objective = plan_objective(
            new_coverage, new_oar,
            seed_count=int(seed_count),
            needle_count=int(needle_count),
            target_coverage=self.DVH_rate,
        )
        return float(new_objective - old_objective)


# ==========================================================
# 2.  Policy Network
# ==========================================================
class PolicyNet(nn.Module):
    """MLP policy for discrete actions, conditioned on a real state vector.

    The previous network consumed a constant placeholder state, which collapsed
    the policy to a static categorical prior.  With a real state dimension the
    hidden activations - and therefore every action logit - depend on the plan
    state (coverage, OAR burden, budget usage).
    """
    def __init__(self, n_actions, hidden=128, state_dim=1):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(state_dim, hidden), nn.ReLU(),
            nn.Linear(hidden, hidden), nn.ReLU()
        )
        self.logits = nn.Linear(hidden, n_actions)

    def forward(self, s):
        return self.logits(self.net(s))

    def act(self, s):
        logits = self(s)
        dist = Categorical(logits=logits)
        a = dist.sample()
        return a, dist.log_prob(a)


# ==========================================================
# 3.  REINFORCE Agent (vectorized loss)
# ==========================================================
class REINFORCE:
    def __init__(self, n_actions, lr=1e-2, gamma=0.99, device="cpu", state_dim=1):
        self.device = torch.device(device)
        self.state_dim = int(state_dim)
        self.policy = PolicyNet(n_actions, state_dim=self.state_dim).to(self.device)
        self.optimizer = optim.Adam(self.policy.parameters(), lr=lr)
        self.gamma = gamma
        self.log_probs = []
        self.rewards = []

    # ------------------------------------------------------
    def select_action(self, state, mask=None):
        """Return action index (int) and store log_prob."""
        state_array = np.asarray(state, dtype=np.float32).reshape(-1)
        if state_array.size != self.state_dim:
            padded = np.zeros(self.state_dim, dtype=np.float32)
            padded[: min(self.state_dim, state_array.size)] = state_array[: self.state_dim]
            state_array = padded
        s = torch.from_numpy(state_array).unsqueeze(0).to(self.device)
        logits = self.policy(s)  # shape [1, n_actions]

        if mask is not None:
            # mask is numpy boolean array of length n_actions
            # convert once to a tensor on correct device
            mask_tensor = torch.from_numpy(mask.astype(bool)).to(self.device)
            # set invalid logits to a large negative value
            logits = logits.clone()
            logits[..., ~mask_tensor] = -1e10

        dist = Categorical(logits=logits)
        a = dist.sample()
        self.log_probs.append(dist.log_prob(a))
        return a.item()

    # ------------------------------------------------------
    def record_reward(self, r):
        self.rewards.append(r)

    # ------------------------------------------------------
    def finish_episode(self):
        """Compute discounted returns and update policy."""
        if not self.rewards:
            # nothing to update
            self.log_probs.clear()
            return

        # compute discounted returns
        returns = []
        R = 0.0
        for r in reversed(self.rewards):
            R = r + self.gamma * R
            returns.insert(0, R)
        returns = torch.tensor(returns, dtype=torch.float32, device=self.device)

        # normalize if more than 1 value
        if len(returns) > 1:
            returns = (returns - returns.mean()) / (returns.std() + 1e-8)

        log_probs_tensor = torch.stack(self.log_probs)
        loss = - (log_probs_tensor * returns).sum()

        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()

        self.log_probs.clear()
        self.rewards.clear()


# ==========================================================
# 4.  Low-level Environment
# ==========================================================
class LowLevelEnv(gym.Env):
    """
    Low-level env: pick candidate positions along a fixed needle path.
    """
    def __init__(self, candidate_positions, max_steps=None):
        super().__init__()
        self.candidate_positions = candidate_positions
        self.used_mask = np.ones(len(candidate_positions), dtype=bool)  # True = available
        self.cur_step = 0
        self.done = False
        requested_max_steps = len(candidate_positions) if max_steps is None else int(max_steps)
        candidate_count = len(candidate_positions)
        self.max_steps = max(1, min(candidate_count, requested_max_steps)) if candidate_count else 0
        # Gym requires ``n >= 1`` even though an empty candidate space is
        # immediately completed by the caller before an action is selected.
        self.action_space = spaces.Discrete(max(1, candidate_count))
        self.observation_space = spaces.Box(low=0, high=1, shape=(1,), dtype=np.float32)

    # ------------------------------------------------------
    def reset(self):
        self.used_mask[:] = True
        self.cur_step = 0
        self.done = False
        return np.array([0.0], dtype=np.float32)

    # ------------------------------------------------------
    def step(self, action):
        # mark used and advance
        self.used_mask[action] = False
        self.cur_step += 1
        if not self.used_mask.any() or self.cur_step >= self.max_steps:
            self.done = True
        # keep same return signature as original code expects: (state, done, {})
        return np.array([0.0], dtype=np.float32), self.done, {}


# ==========================================================
# 5.  High-level Environment
# ==========================================================
class HighLevelEnv(gym.Env):
    """
    High-level env: select trajectory group, then run low-level RL to place seeds.
    """
    def __init__(self,
                 target_level_traj,
                 high_level_ranges,
                 low_level_ranges,
                 range_length,
                 target_level,
                 dose_image,
                 radiation_volume,
                 seed_info,
                 reward_calculator,
                 DVH_rate,
                 protect_OAR,
                 max_actions_per_episode=None,
                 deadline=None):
        super().__init__()
        self.level = target_level
        self.range_length = range_length
        self.cum_sizes = np.cumsum(self.range_length)
        self.action_space = spaces.Discrete(len(high_level_ranges))
        self.observation_space = spaces.Box(low=0, high=1, shape=(1,), dtype=np.float32)

        self.high_level_ranges   = high_level_ranges
        self.target_level_traj   = target_level_traj
        self.low_level_ranges    = low_level_ranges
        self.DVH_rate            = DVH_rate
        self.protect_OAR         = protect_OAR

        self.group_idx = None
        self.dose_image  = dose_image
        self.seed_info   = seed_info
        self.spacing     = np.array(self.dose_image.GetSpacing()).reshape(-1)

        self.planned_positions = [[] for _ in range(self.level)]
        self.planned_seed_radiations = [[] for _ in range(self.level)]
        self.planned_directions = [np.array([0, 0, 1]) for _ in range(self.level)]
        self.cur_radiation = np.zeros_like(radiation_volume, dtype=np.float32)
        self.cur_DVH_rate = 0.0
        self.reward_calculator = reward_calculator
        self.max_actions_per_episode = max_actions_per_episode
        self.deadline = deadline
        # One low-level policy per trajectory group.  The nested agents used to
        # be created and thrown away inside every high-level step, so their
        # Adam updates could never accumulate any learning.
        self.low_agents = {}
        self.prefetched_groups = set()

        # Precompute candidate positions (img coords and world coords) per group and level
        # Structure:
        # candidate_img_positions[(group_idx, lv)] = np.array([img_pos for length in effective_range])
        # candidate_world_positions[(group_idx, lv)] = np.array([...]) (same shape)
        self.candidate_img_positions = {}
        self.candidate_world_positions = {}
        self._precompute_candidate_positions()
      
    # ------------------------------------------------------    
    def _precompute_candidate_positions(self):
        """Precompute and cache image/world positions for every group/level/length."""
        for group_idx, group in enumerate(self.target_level_traj):
            for lv in range(self.level):
                slicer.app.processEvents()
                traj = group[lv][1]
                point = np.array(traj[0]).reshape(-1)
                direction = np.array(traj[1]).reshape(-1)
                direction = direction / np.linalg.norm(direction)
                max_idx = np.argmax(np.abs(direction))
                update_dir = direction / np.abs(direction[max_idx])

                effective_range = self.low_level_ranges[group_idx][lv]
                # compute img positions
                img_positions = np.stack([point + update_dir * length for length in effective_range], axis=0)
                # try to use batch transform if available; fallback to loop
                try:
                    world_positions = np.array(utilizations.position_transform(self.dose_image, img_positions))
                    # position_transform may return list of tuples; normalize to array of points
                    # assume returns array-like shape (N, 3) or list of length N each a 3-vector
                    if world_positions.ndim == 3:
                        # sometimes transforms return [[(x,y,z)]] shape; try to squeeze
                        world_positions = world_positions.squeeze()
                except Exception:
                    # fallback: transform point-by-point
                    world_positions = np.array([utilizations.position_transform(self.dose_image, img_pos)[0] for img_pos in img_positions])

                self.candidate_img_positions[(group_idx, lv)] = img_positions
                self.candidate_world_positions[(group_idx, lv)] = world_positions

    # ------------------------------------------------------
    def reset(self):
        """Reset before new episode."""
        self.group_idx = None
        self.planned_positions = [[] for _ in range(self.level)]
        self.planned_seed_radiations = [[] for _ in range(self.level)]
        self.planned_directions = [np.array([0, 0, 1]) for _ in range(self.level)]
        self.cur_radiation[:] = 0.0
        self.cur_DVH_rate = 0.0
        return np.array([0.0], dtype=np.float32)

    # ------------------------------------------------------
    def generate_low_level_state_space(self, action):
        """Flatten all low-level candidates for the chosen trajectory group."""
        # keep original logic for group_idx computation
        self.group_idx = np.searchsorted(self.cum_sizes, action, side="right") // self.level
        merged = []
        for lv in range(self.level):
            merged.extend(self.low_level_ranges[self.group_idx][lv])
        return merged

    # ------------------------------------------------------
    def generate_mask(self, used_mask=None):
        """
        Build boolean mask for low-level actions.
        True  = position is available (not inside exclusion zone).
        False = position is forbidden.
        Uses precomputed candidate_world_positions for speed.
        """
        trajs = self.target_level_traj[self.group_idx]
        mask = []
        # iterate levels
        for lv in range(self.level):
            slicer.app.processEvents()
            cur_traj = trajs[lv][1]
            point = np.array(cur_traj[0]).reshape(-1)
            world_p = utilizations.position_transform(self.dose_image, point)[0]
            effective_range = self.low_level_ranges[self.group_idx][lv]

            # start all True
            lv_mask = np.ones(len(effective_range), dtype=bool)

            # If there are existing planned positions at this lv, vectorize distance checks
            if self.planned_positions[lv]:
                all_pos = self.candidate_world_positions[(self.group_idx, lv)]  # shape (N, 3)
                # For each already planned position, compute blocked indices
                planned_arr = np.array(self.planned_positions[lv])  # shape (M,3)
                # compute distances from planned positions to world_p
                # but original logic uses dist between planned_pos and world_p to set a start/end, then
                # compares candidate distances to world_p against that start/end.
                # So do this vectorized:
                dists_planned_to_world_p = np.linalg.norm(planned_arr - world_p, axis=1)  # (M,)
                # compute candidate distances to world_p once
                candidate_dists = np.linalg.norm(all_pos - world_p, axis=1)  # (N,)
                # For each planned, set mask false where candidate_dists in (start, end)
                for dist in dists_planned_to_world_p:
                    start = dist - self.seed_info['length']
                    end = dist + self.seed_info['length']
                    # vectorized boolean update
                    lv_mask[(candidate_dists > start) & (candidate_dists < end)] = False

            mask.extend(lv_mask)
        mask = np.array(mask, dtype=bool)
        if used_mask is not None:
            used_mask = np.asarray(used_mask, dtype=bool)
            if used_mask.shape != mask.shape:
                raise ValueError(
                    f"Low-level action mask shape mismatch: {used_mask.shape} vs {mask.shape}"
                )
            # Geometric exclusion is not the only convergence mechanism.  A
            # selected action is always retired even if a malformed seed length
            # would otherwise leave its position geometrically available.
            mask &= used_mask
        return mask

    # ------------------------------------------------------
    def activate_group(self, group_idx, device="cpu"):
        """Prefetch the group's single-seed dose maps and restore its policy.

        The batched DoseUNet call replaces the per-step single forward passes;
        the group's REINFORCE agent is created once and kept so its updates
        accumulate across episodes instead of being discarded.
        """
        group_idx = int(group_idx)
        if group_idx not in self.prefetched_groups:
            # The dense stage already inferred these dose maps; importing them
            # first turns the batched prefetch below into pure cache hits and
            # removes one redundant DoseUNet sweep per group.
            for lv in range(self.level):
                self.reward_calculator.import_trajectory_dose_maps(
                    self.target_level_traj[group_idx][lv])
            candidates = []
            for lv in range(self.level):
                positions = self.candidate_img_positions.get((group_idx, lv))
                if positions is None or len(positions) == 0:
                    continue
                traj = self.target_level_traj[group_idx][lv][1]
                direction = np.array(traj[1], dtype=np.float64).reshape(-1)
                direction = direction / np.linalg.norm(direction)
                for img_position in positions:
                    candidates.append((img_position, direction))
            if candidates:
                self.reward_calculator.prefetch_positions(candidates)
            self.prefetched_groups.add(group_idx)
        merged_size = sum(len(self.low_level_ranges[group_idx][lv]) for lv in range(self.level))
        agent = self.low_agents.get(group_idx)
        if agent is None:
            agent = REINFORCE(
                n_actions=max(1, merged_size),
                device=device,
                state_dim=POLICY_STATE_DIM,
            )
            self.low_agents[group_idx] = agent
        return agent

    def policy_state(self, low_env):
        """Real state for the low-level policy (coverage, damage, budget, freedom)."""
        remaining = 0.0
        try:
            remaining = float(np.count_nonzero(low_env.used_mask)) / max(1, low_env.used_mask.size)
        except Exception:
            remaining = 0.0
        return np.array([
            min(1.5, float(self.cur_DVH_rate) / max(float(self.DVH_rate), 1e-6)),
            min(1.0, float(getattr(self.reward_calculator, "last_out_damage", 0.0) or 0.0)),
            float(low_env.cur_step) / max(1.0, float(low_env.max_steps or 1)),
            remaining,
        ], dtype=np.float32)

    # ------------------------------------------------------
    def update_planned_position(self, action, high_level=False):
        """
        Convert action (high or low) to world position, store it, and return incremental reward.
        Uses precomputed candidate positions.
        """
        if high_level:
            lv = np.searchsorted(self.cum_sizes, action, side="right") % self.level
        else:
            lv = np.searchsorted(np.cumsum(self.range_length[self.group_idx * self.level:]), action, side="right") % self.level

        traj = self.target_level_traj[self.group_idx][lv][1]
        point = np.array(traj[0]).reshape(-1)
        direction = np.array(traj[1]).reshape(-1)
        direction = direction / np.linalg.norm(direction)
        max_idx = np.argmax(np.abs(direction))
        update_dir = direction / np.abs(direction[max_idx])

        # select length depending on action (high/low)
        if high_level:
            length = self.high_level_ranges[action]
            # compute img position (not necessarily in candidate lists)
            img_position = np.array(update_dir * length + point)
            # get world position via transform
            world_position = utilizations.position_transform(self.dose_image, img_position)[0]
        else:
            # for low-level action, action is index in flattened low-level state space
            length = self.low_level_state_space[action]
            # use cached candidate positions for this group/lv
            # find index inside effective_range
            effective_range = self.low_level_ranges[self.group_idx][lv]
            # length may appear multiple times but indices align; find index position
            # attempt to find first index matching length
            try:
                idx_in_lv = list(effective_range).index(length)
            except ValueError:
                # fallback compute
                img_position = np.array(update_dir * length + point)
                world_position = utilizations.position_transform(self.dose_image, img_position)[0]
            else:
                img_position = self.candidate_img_positions[(self.group_idx, lv)][idx_in_lv]
                world_position = self.candidate_world_positions[(self.group_idx, lv)][idx_in_lv]

        is_new_needle = not self.planned_positions[lv]
        seed_count = 1 + sum(len(entry) for entry in self.planned_positions)
        needle_count = sum(1 for entry in self.planned_positions if entry) + (1 if is_new_needle else 0)
        reward, self.cur_radiation, cur_DVH_rate, cur_seed_radiation = self.reward_calculator.forward(
            traj=self.target_level_traj[self.group_idx][lv],
            cur_radiation=self.cur_radiation,
            direction=direction,
            seed_point=img_position,
            protect_OAR=self.protect_OAR,
            seed_count=seed_count,
            needle_count=needle_count,
            is_new_needle=is_new_needle,
        )
        self.cur_DVH_rate = cur_DVH_rate
        if cur_seed_radiation is None:
            # Failed dose prediction: retire the action but never fabricate a
            # zero-dose seed inside the plan.
            return 0.0, cur_DVH_rate

        self.planned_positions[lv].append(world_position)
        self.planned_seed_radiations[lv].append(cur_seed_radiation)
        self.planned_directions[lv] = np.array(utilizations.direction_transform(self.dose_image, direction))[0]
        return reward, cur_DVH_rate
    
    # ------------------------------------------------------
    def planned_position2planned_res(self):
        """
        Convert internally stored planned seed positions (world coordinates) into
        the canonical 'planned_res' format used downstream.
        """
        planned_res = []

        for lv in range(self.level):
            slicer.app.processEvents()
            seeds = []
            single_seed_radiations = []

            for position, single_seed_radiation in zip(
                self.planned_positions[lv], self.planned_seed_radiations[lv]
            ):
                seeds.append([position, self.planned_directions[lv]])
                single_seed_radiations.append(single_seed_radiation)

            trajectory_def = self.target_level_traj[self.group_idx][lv][1]
            planned_res.append([trajectory_def, seeds, single_seed_radiations])

        return planned_res

    # ------------------------------------------------------
    def _action_geometry(self, action, high_level=False):
        """Resolve (level, img position, direction, world position) for one action."""
        if high_level:
            lv = np.searchsorted(self.cum_sizes, action, side="right") % self.level
            length = self.high_level_ranges[action]
        else:
            lv = np.searchsorted(
                np.cumsum(self.range_length[self.group_idx * self.level:]),
                action, side="right") % self.level
            length = self.low_level_state_space[action]
        traj = self.target_level_traj[self.group_idx][lv][1]
        point = np.array(traj[0]).reshape(-1)
        direction = np.array(traj[1]).reshape(-1)
        direction = direction / np.linalg.norm(direction)
        max_idx = np.argmax(np.abs(direction))
        update_dir = direction / np.abs(direction[max_idx])
        effective_range = self.low_level_ranges[self.group_idx][lv]
        try:
            idx_in_lv = list(effective_range).index(length)
        except ValueError:
            img_position = np.array(update_dir * length + point)
            world_position = utilizations.position_transform(self.dose_image, img_position)[0]
        else:
            img_position = self.candidate_img_positions[(self.group_idx, lv)][idx_in_lv]
            world_position = self.candidate_world_positions[(self.group_idx, lv)][idx_in_lv]
        return lv, np.asarray(img_position).reshape(-1), direction, world_position

    def evaluate_action_marginal(self, action):
        """Non-committing objective gain of one low-level action (greedy ranking)."""
        lv, img_position, direction, _ = self._action_geometry(action, high_level=False)
        key = SeedPlacementReward.cache_key_for(img_position, direction)
        dose_map = self.reward_calculator.seed_cache.get(key)
        if dose_map is None:
            return -np.inf
        is_new_needle = not self.planned_positions[lv]
        seed_count = 1 + sum(len(entry) for entry in self.planned_positions)
        needle_count = sum(1 for entry in self.planned_positions if entry) + (1 if is_new_needle else 0)
        return self.reward_calculator.evaluate_marginal(
            self.cur_radiation,
            dose_map,
            seed_count=seed_count,
            needle_count=needle_count,
            is_new_needle=is_new_needle,
            protect_OAR=self.protect_OAR,
        )

    def run_greedy(self, group_idx, device="cpu", restarts=3):
        """Deterministic marginal-gain warm start on one trajectory group.

        Repeatedly place the candidate with the highest remaining objective
        gain and stop when no candidate improves the plan objective (the seed
        cost then makes 'stop' the optimal move).  Several deterministic
        restarts (forced first seeds ranked by their one-step gain) recover
        from the classic greedy myopia of grabbing a whole lobe first, so the
        incumbent can only improve.  The plan enters the incumbent pool and
        the returned result is the best restart.
        """
        ranked = []
        for restart in range(max(1, int(restarts))):
            if self.deadline is not None and time.monotonic() >= self.deadline:
                break
            plan, reward, coverage = self._greedy_pass(group_idx, device, restart=restart)
            ranked.append((reward, coverage, plan))
        if not ranked:
            return [], -np.inf, 0.0
        ranked.sort(key=lambda item: item[0], reverse=True)
        best_reward, best_coverage, best_plan = ranked[0]
        return best_plan, best_reward, best_coverage

    def _greedy_pass(self, group_idx, device="cpu", restart=0):
        """One greedy sweep.  ``restart`` forces the n-th best first seed."""
        self.reset()
        self.group_idx = int(group_idx)
        self.activate_group(self.group_idx, device=device)
        merged = []
        for lv in range(self.level):
            merged.extend(self.low_level_ranges[self.group_idx][lv])
        self.low_level_state_space = merged
        n_actions = len(merged)
        if n_actions == 0:
            return [], -np.inf, 0.0
        available = np.ones(n_actions, dtype=bool)
        budget = n_actions if not self.max_actions_per_episode else min(
            n_actions, int(self.max_actions_per_episode))
        total_reward = 0.0
        cur_DVH_rate = 0.0
        placed = 0
        forced = None
        if restart > 0:
            first_gains = []
            for a in range(n_actions):
                if self.deadline is not None and time.monotonic() >= self.deadline:
                    break
                first_gains.append((self.evaluate_action_marginal(int(a)), int(a)))
            first_gains.sort(key=lambda item: (-item[0], item[1]))
            if restart < len(first_gains):
                forced = first_gains[restart][1]
        while placed < budget:
            if self.deadline is not None and time.monotonic() >= self.deadline:
                break
            slicer.app.processEvents()
            mask = self.generate_mask(available)
            if not mask.any():
                break
            best_action, best_gain = None, -np.inf
            if forced is not None:
                if not mask[forced]:
                    forced = None
                else:
                    best_action, best_gain = forced, self.evaluate_action_marginal(forced)
                    forced = None
            if best_action is None:
                scanned = 0
                for candidate in np.flatnonzero(mask):
                    scanned += 1
                    if self.deadline is not None and scanned % 16 == 0 and time.monotonic() >= self.deadline:
                        break
                    gain = self.evaluate_action_marginal(int(candidate))
                    if gain > best_gain:
                        best_gain, best_action = gain, int(candidate)
                if self.deadline is not None and time.monotonic() >= self.deadline and best_action is None:
                    break
            if best_action is None or best_gain <= 0.0:
                break
            reward, cur_DVH_rate = self.update_planned_position(best_action, high_level=False)
            total_reward += reward
            available[best_action] = False
            placed += 1
            if cur_DVH_rate >= self.DVH_rate:
                break
        return self.planned_position2planned_res(), total_reward, cur_DVH_rate

    # ------------------------------------------------------
    def step(self, action, device="cpu"):
        """
        Execute high-level action, then run full low-level episode.
        Returns:
            total_reward (float), plan_tuple (high_action, planned_positions)
        """
        try:
            self.low_level_state_space = self.generate_low_level_state_space(action)
            low_agent = self.activate_group(self.group_idx, device=device)
            low_env = LowLevelEnv(
                self.low_level_state_space,
                max_steps=self.max_actions_per_episode,
            )
            low_env.reset()

            # Keep the initial high-level seed's coverage.  Dropping this
            # value made a one-seed valid plan look like V100=0 whenever the
            # low-level action space was exhausted immediately.
            total_reward, cur_DVH_rate = self.update_planned_position(action, high_level=True)
            self.cur_DVH_rate = cur_DVH_rate

            mask = None
            while not low_env.done:
                try:
                    if self.deadline is not None and time.monotonic() >= self.deadline:
                        low_env.done = True
                        break
                    slicer.app.processEvents()
                    mask = self.generate_mask(low_env.used_mask)
                    if mask.any():
                        state = self.policy_state(low_env)
                        a = low_agent.select_action(state, mask=mask)
                        low_env.step(a)
                        r, cur_DVH_rate = self.update_planned_position(a, high_level=False)
                        low_agent.record_reward(r)
                        total_reward += r
                        self.cur_DVH_rate = cur_DVH_rate
                        if cur_DVH_rate >= self.DVH_rate:
                            low_env.done = True
                    else:
                        low_env.done = True
                except DoseInferenceDeadlineExceeded:
                    raise
                except Exception:
                    logger.debug("Low-level environment step failed", exc_info=True)
                    low_env.done = True

            planned_res = self.planned_position2planned_res()
            return total_reward, planned_res, cur_DVH_rate, mask, self.group_idx, self.low_level_state_space, low_env, low_agent
        except DoseInferenceDeadlineExceeded:
            raise
        except Exception:
            logger.debug("High-level environment step failed", exc_info=True)
            planned_res = self.planned_position2planned_res() if self.group_idx is not None else []
            fallback_agent = self.low_agents.get(self.group_idx) if self.group_idx is not None else None
            return (
                -np.inf,
                planned_res,
                0.0,
                None,
                self.group_idx,
                self.low_level_state_space if hasattr(self, 'low_level_state_space') else [],
                LowLevelEnv([]),
                fallback_agent or REINFORCE(1, state_dim=POLICY_STATE_DIM),
            )



def evaluate_plan_objective(
    plan_res,
    radiation_volume,
    target_value,
    in_lowest_dose,
    out_highest_dose,
    DVH_rate,
):
    """Return the final RL objective and V100-style coverage for a full plan.

    A single seed's incremental reward is useful for updating a policy, but it
    is not a valid way to rank complete plans: the last seed can have a small
    marginal gain while the accumulated plan is the best one.  This helper is
    deliberately based on the stored AI dose maps, so selection uses the same
    final dose representation that downstream DVH evaluation receives.
    """
    total_radiation = np.zeros_like(radiation_volume, dtype=np.float32)
    for entry in plan_res or []:
        if not isinstance(entry, (list, tuple)) or len(entry) < 3:
            continue
        for single_seed_radiation in entry[2] or []:
            dose = np.asarray(single_seed_radiation, dtype=np.float32)
            if dose.shape != total_radiation.shape:
                raise ValueError(
                    "RL plan contains a dose map whose geometry differs from the planning grid"
                )
            total_radiation += dose

    target_mask = radiation_volume == target_value
    target_count = int(np.count_nonzero(target_mask))
    if target_count <= 0:
        return -np.inf, 0.0

    coverage = float(
        np.count_nonzero(total_radiation[target_mask] > float(in_lowest_dose))
    ) / target_count
    non_target_mask = ~target_mask
    out_damage = normalized_oar_damage(
        int(np.count_nonzero(total_radiation[non_target_mask] > float(out_highest_dose))),
        target_count,
    )
    seed_count, needle_count = plan_cost_counts(plan_res)
    objective = plan_objective(
        coverage,
        out_damage,
        seed_count=seed_count,
        needle_count=needle_count,
        target_coverage=float(DVH_rate),
    )
    return float(objective), coverage


def plan_cost_counts(plan_res):
    """Return (seed_count, needle_count) for a planned result.

    A needle counts once when it carries seeds or dose maps; an entry whose
    seed list is empty falls back to its dose-map count so serialized plans
    stay comparable with live episode plans.
    """
    seeds = 0
    needles = 0
    for entry in plan_res or []:
        if not isinstance(entry, (list, tuple)) or len(entry) < 3:
            continue
        entry_seeds = entry[1] if isinstance(entry[1], (list, tuple)) else []
        entry_maps = entry[2] if isinstance(entry[2], (list, tuple)) else []
        count = len(entry_seeds) if entry_seeds else len(entry_maps)
        seeds += int(count)
        if count:
            needles += 1
    return seeds, needles


def _trajectory_advance(traj):
    """Return (point, unit-ish advance vector) used for seed stepping."""
    point = np.asarray(traj[0], dtype=np.float64).reshape(-1)
    direction = np.asarray(traj[1], dtype=np.float64).reshape(-1)
    direction = direction / max(float(np.linalg.norm(direction)), 1e-12)
    max_index = int(np.argmax(np.abs(direction)))
    dominant = float(np.abs(direction[max_index]))
    advance = direction / max(dominant, 1e-12)
    return point, direction, advance


def _slot_positions(traj, steps):
    point, _, advance = _trajectory_advance(traj)
    return [np.asarray(point + float(step) * advance, dtype=np.float64).reshape(-1)
            for step in steps]


def construct_plan_over_candidates(
        reward_calculator,
        candidate_trajectories,
        radiation_volume,
        target_value,
        dose_image,
        distance_map,
        seed_info,
        *,
        interval_rate=2.0,
        deadline=None,
        protect_OAR=True,
        parallel_min_distance_mm=None,
        parallel_angle_tolerance_deg=None,
        preview_callback=None):
    """Deterministic sequential construction over the FULL candidate pool.

    The hierarchical combo space can express at most ``max_hierarchy_depth``
    needles drawn from one trajectory sub-sample, which structurally caps
    every learning-phase plan far below what large cases need (the 238 cm3
    regression case needs ~24 needles while combos capped at 8).  This phase
    builds the plan one spacing-safe needle at a time from the full
    safety-validated pool and places, on each needle, only the seed slots with
    positive marginal plan-objective gain (dose inference batched through the
    shared seed cache).  It stops at target coverage, its deadline, or when no
    candidate adds objective value, and every accepted step strictly improves
    the same :func:`plans.reward_metrics.plan_objective` used for selection.

    Returns the plan in the canonical ``[trajectory, world_seeds, dose_maps]``
    form; an expired deadline returns whatever was built so far (``[]`` when
    nothing was accepted).
    """
    candidates = list(candidate_trajectories or [])
    if not candidates:
        return []
    if deadline is not None and time.monotonic() >= deadline:
        return []

    def _expired():
        return deadline is not None and time.monotonic() >= deadline

    base_threshold = 2.0 * float(seed_info.get('radius', 0.4)) * float(interval_rate)
    in_lowest_dose = float(reward_calculator.in_lowest_dose)
    target_coverage = float(reward_calculator.DVH_rate)

    # Per-candidate seed slots depend only on the trajectory's own geometry,
    # so compute them once instead of rescoring from scratch every round.
    slot_steps = []
    slot_points = []
    slot_directions = []
    capacity_bonus = np.zeros(len(candidates), dtype=np.float64)
    for index, traj in enumerate(candidates):
        if _expired():
            return []
        steps = list(utilizations.get_available_position(
            traj, [], seed_info, dose_image, distance_map))
        _, direction, _ = _trajectory_advance(traj)
        slot_steps.append(steps)
        slot_points.append(_slot_positions(traj, steps))
        slot_directions.append(direction)
        capacity_bonus[index] = min(1.0, max(0.0, (len(steps) - 1) / 3.0))

    planned = []
    plan_entries = []
    used = np.zeros(len(candidates), dtype=bool)
    cur_radiation = np.zeros_like(radiation_volume, dtype=np.float32)
    cur_coverage = 0.0
    total_seeds = 0

    while not _expired() and cur_coverage < target_coverage:
        best_index, best_score = None, 0.0
        for index, traj in enumerate(candidates):
            if used[index] or not slot_steps[index]:
                continue
            if planned:
                safe = utilizations.get_trajectory_spacing_safety_mask(
                    [traj], planned, dose_image,
                    base_min_distance_mm=base_threshold,
                    parallel_min_distance_mm=parallel_min_distance_mm,
                    parallel_angle_tolerance_deg=parallel_angle_tolerance_deg,
                )[0]
                if not safe:
                    used[index] = True
                    continue
            deficit = 0.0
            shape = np.asarray(radiation_volume.shape)
            for point in slot_points[index]:
                coords = np.asarray(point).astype(int)
                if np.any(coords < 0) or np.any(coords >= shape):
                    continue
                deficit += max(0.0, 1.0 - float(cur_radiation[tuple(coords)]) / max(in_lowest_dose, 1e-12))
            score = deficit * (1.0 + 0.12 * float(capacity_bonus[index]))
            if score > best_score:
                best_score, best_index = score, index
        if best_index is None or best_score <= 0.0:
            break

        traj = candidates[best_index]
        direction = slot_directions[best_index]
        steps = list(slot_steps[best_index])
        points = list(slot_points[best_index])
        reward_calculator.prefetch_positions(list(zip(points, [direction] * len(points))))

        placed_points = []
        placed_maps = []
        world_seeds = []
        while steps and not _expired():
            seed_count = total_seeds + 1
            needle_count = len(planned) + 1
            is_new_needle = not placed_points
            best_gain, best_pos = 0.0, None
            for step, point in zip(list(steps), list(points)):
                key = SeedPlacementReward.cache_key_for(point, direction)
                dose_map = reward_calculator.seed_cache.get(key)
                if dose_map is None:
                    continue
                gain = reward_calculator.evaluate_marginal(
                    cur_radiation, dose_map,
                    seed_count=seed_count,
                    needle_count=needle_count,
                    is_new_needle=is_new_needle,
                    protect_OAR=protect_OAR,
                )
                if gain > best_gain:
                    best_gain, best_pos = gain, (step, point, dose_map)
            if best_pos is None or best_gain <= 0.0:
                break
            step, point, _ = best_pos
            reward, cur_radiation, cur_coverage, dose_map = reward_calculator.forward(
                [best_index, traj, [], [], None],
                cur_radiation,
                direction,
                point,
                protect_OAR=protect_OAR,
                seed_count=seed_count,
                needle_count=needle_count,
                is_new_needle=is_new_needle,
            )
            if dose_map is None:
                steps = [s for s in steps if s != step]
                points = _slot_positions(traj, steps)
                continue
            placed_points.append(point)
            placed_maps.append(dose_map)
            world_position = np.asarray(
                utilizations.position_transform(dose_image, point)[0]).reshape(-1)
            world_direction = np.asarray(
                utilizations.direction_transform(dose_image, direction)[0]).reshape(-1)
            world_seeds.append([world_position, world_direction])
            total_seeds += 1
            steps = list(utilizations.get_available_position(
                traj, [(p, direction) for p in placed_points],
                seed_info, dose_image, distance_map))
            points = _slot_positions(traj, steps)
            if cur_coverage >= target_coverage:
                break

        if not placed_points:
            used[best_index] = True
            continue
        used[best_index] = True
        planned.append(traj)
        plan_entries.append([traj, world_seeds, placed_maps])
        safe_preview(preview_callback, {
            "phase": "rl_plan_construction",
            "iteration": len(planned),
            "coverage": cur_coverage,
            "coordinate_space": "world",
            "plan": [plan_entries[-1]],
            "force": False,
        })

    return plan_entries


def generate_baseline_state_space(low_level_state_spaces, level, idx):
    merged = []
    for lv in range(level):
        merged.extend(low_level_state_spaces[idx][lv])
    return merged



def generate_plan_res(dose_image, elem):
    planned_res = []
    for _, traj, seeds, single_seed_radiations, _ in elem:
        slicer.app.processEvents()
        direction = np.asarray(
            utilizations.direction_transform(dose_image, np.array(traj[1]).reshape(-1))[0]
        ).reshape(-1)
        world_seeds = []
        for _, seed in enumerate(seeds):
            position = np.asarray(
                utilizations.position_transform(dose_image, seed[0])[0]
            ).reshape(-1)
            world_seeds.append([position, direction])
        planned_res.append([traj, world_seeds, single_seed_radiations])
    return planned_res


# ==========================================================
# 6.  Top-level optimisation loop (kept logic, improved small parts)
# ==========================================================
def reinforcement_planning(
        rf_params,
        dose_cal_model,
        dose_image,
        radiation_volume,
        target_value,
        target_level_traj,
        high_level_state_spaces,
        low_level_state_spaces,
        range_length,
        target_level,
        seed_info,
        in_lowest_dose,
        out_highest_dose,
        infer_img_size,
        image_normalize_min,
        image_normalize_max,
        image_normalize_scale,
        DVH_rate,
        progressDialog,
        deadline=None,
        max_actions_per_episode=None,
        diagnostics=None,
        preview_callback=None,
        construction_candidates=None,
        distance_map=None,
        interval_rate=2.0,
        parallel_min_distance_mm=None,
        parallel_angle_tolerance_deg=None):
    """
    Hierarchical reinforcement learning driver for a single patient case.
    Logic preserved; internal calls use optimized env and caches.
    """
    # Initialize the recovery state before any model access so the exception
    # path can always return a valid result instead of masking the root error.
    best_plan = None
    best_reward = -np.inf
    rl_status = diagnostics if isinstance(diagnostics, dict) else None
    if rl_status is not None and "schema_version" not in rl_status:
        initial = new_rl_status(DVH_rate)
        initial.update(rl_status)
        rl_status.clear()
        rl_status.update(initial)

    def _emit_preview(plan, phase, iteration, coverage, reward, force=False):
        safe_preview(preview_callback, {
            "phase": phase,
            "iteration": iteration,
            "coverage": coverage,
            "reward": reward,
            "coordinate_space": "world",
            "plan": plan or [],
            "force": bool(force),
        })

    def _status_counter(key, amount=1):
        if rl_status is None:
            return
        try:
            rl_status[key] = max(0, int(rl_status.get(key) or 0) + int(amount))
        except (TypeError, ValueError):
            rl_status[key] = max(0, int(amount))

    def _record_plan(coverage, reward):
        update_best(rl_status, coverage, reward)
        if rl_status is not None and float(coverage or 0.0) >= float(DVH_rate):
            set_outcome(
                rl_status,
                execution="completed",
                stop_reason="target_reached",
            )

    def _wall_clock_stop():
        set_outcome(
            rl_status,
            execution="interrupted",
            stop_reason="wall_clock_budget",
        )

    if rl_status is not None:
        rl_status["max_episodes"] = int(rf_params.get("max_episodes", 0) or 0)
        rl_status["max_actions_per_episode"] = int(max_actions_per_episode or 0)
        rl_status["hierarchical_optimization"] = bool(
            rf_params.get("hierarchical_optimization", True)
        )
    try:
        device = next(dose_cal_model.parameters()).device

        # Reproducible search: the same case and the same rf_params must plan
        # the same seeds.  ``random_seed: null`` restores the old unseeded
        # exploration for research runs.
        random_seed = rf_params.get("random_seed", 0)
        if random_seed is not None:
            seed_int = int(random_seed)
            np.random.seed(seed_int)
            torch.manual_seed(seed_int)
            if torch.cuda.is_available():
                torch.cuda.manual_seed_all(seed_int)

        protect_oar = bool(rf_params.get("segmented_rewards", True))
        hierarchical_mode = bool(rf_params.get("hierarchical_optimization", True))
        max_episodes = int(rf_params.get("max_episodes", 200) or 0)

        high_agent = REINFORCE(
            n_actions=len(high_level_state_spaces),
            lr=float(rf_params.get('lr', 1e-3)),
            gamma=float(rf_params.get('gamma', 0.99)),
            device=device
        )

        reward_calculator = SeedPlacementReward(
            dose_cal_model, dose_image, radiation_volume, target_value,
            in_lowest_dose, out_highest_dose, infer_img_size, seed_info,
            image_normalize_min, image_normalize_max,
            image_normalize_scale, DVH_rate, deadline=deadline
        )

        env = HighLevelEnv(
            target_level_traj, high_level_state_spaces, low_level_state_spaces,
            range_length, target_level, dose_image, radiation_volume,
            seed_info, reward_calculator, DVH_rate, protect_oar,
            max_actions_per_episode=max_actions_per_episode,
            deadline=deadline,
        )

        best_group_idx = None
        best_low_level_state_space = None
        best_low_env = None
        best_low_agent = None
        group_objectives = {}

        for idx, elem in enumerate(target_level_traj):
            if deadline is not None and time.monotonic() >= deadline:
                logger.warning("[rl] Baseline trajectory scoring reached its wall-clock budget")
                _wall_clock_stop()
                break
            try:
                progressDialog.setValue(65)
                progressDialog.setLabelText("Learning-based Planning...")
                slicer.app.processEvents()
                
                trajs_radiations = np.zeros_like(radiation_volume, dtype=np.float32)
                dense_seed_count = 0
                for entry in elem:
                    trajs_radiations += entry[4]
                    dense_seed_count += len(entry[2] or [])
                target_sum = np.sum(trajs_radiations * reward_calculator.mask_volume > in_lowest_dose)
                cur_DVH_rate = target_sum / reward_calculator.target_v
                non_target_sum = np.count_nonzero(
                    (trajs_radiations * reward_calculator.non_target_mask > out_highest_dose)
                )
                cur_out_damage = normalized_oar_damage(
                    non_target_sum, reward_calculator.target_v
                ) if protect_oar else 0.0
                cur_reward = plan_objective(
                    cur_DVH_rate,
                    cur_out_damage,
                    seed_count=dense_seed_count,
                    needle_count=len(elem),
                    target_coverage=DVH_rate,
                )
                group_objectives[idx] = float(cur_reward)

                if cur_reward > best_reward:
                    best_reward = cur_reward
                    best_plan = generate_plan_res(dose_image, elem)
                    best_group_idx = idx
                    best_low_level_state_space = generate_baseline_state_space(
                        low_level_state_spaces, target_level, idx
                    )
                    _emit_preview(
                        best_plan, "rl_baseline_selection", idx + 1,
                        cur_DVH_rate, cur_reward,
                    )
                _record_plan(cur_DVH_rate, cur_reward)
                del trajs_radiations
            except Exception:
                logger.debug("Initial RL trajectory evaluation failed", exc_info=True)
                continue

        # Guard: if no valid trajectory was found, return early
        if best_low_level_state_space is None or best_plan is None:
            set_outcome(
                rl_status,
                execution="failed",
                stop_reason="no_available_action",
            )
            return [], -np.inf

        best_low_env = LowLevelEnv(
            best_low_level_state_space,
            max_steps=max_actions_per_episode,
        )
        best_low_agent = env.activate_group(best_group_idx, device=device)

        def _greedy_incumbent(group_idx, phase):
            """Deterministic warm start that can only improve the incumbent pool."""
            nonlocal best_plan, best_reward
            if group_idx is None:
                return
            try:
                env.reset()
                greedy_plan, _greedy_reward, _greedy_coverage = env.run_greedy(group_idx, device=device)
            except DoseInferenceDeadlineExceeded:
                logger.warning("[rl] Greedy warm start stopped at the DoseUNet deadline")
                set_outcome(
                    rl_status,
                    execution="interrupted",
                    stop_reason="dose_inference_deadline",
                )
                return
            except Exception:
                logger.debug("Greedy warm start failed", exc_info=True)
                return
            if not greedy_plan:
                return
            greedy_score, greedy_coverage = evaluate_plan_objective(
                greedy_plan,
                radiation_volume,
                target_value,
                in_lowest_dose,
                out_highest_dose,
                DVH_rate,
            )
            if greedy_score > best_reward:
                best_reward = greedy_score
                best_plan = greedy_plan
                logger.debug(
                    "[rl] greedy warm start incumbent: objective=%.4f coverage=%.4f",
                    greedy_score, greedy_coverage,
                )
                _emit_preview(
                    best_plan, phase, 0,
                    greedy_coverage, greedy_score,
                )
            _record_plan(greedy_coverage, greedy_score)

        def _construction_incumbent():
            """Full-pool sequential construction: the deterministic success path.

            The hierarchical episode space can express at most one combo of
            ``target_level`` needles, so it can never build the 20+ needle
            plans large cases clinically require.  Construction iterates the
            full safety-validated pool and only loses its incumbent role when
            a later episode strictly beats its objective.
            """
            nonlocal best_plan, best_reward
            try:
                constructed = construct_plan_over_candidates(
                    reward_calculator,
                    construction_candidates,
                    radiation_volume,
                    target_value,
                    dose_image,
                    distance_map,
                    seed_info,
                    interval_rate=float(interval_rate or 2.0),
                    deadline=deadline,
                    protect_OAR=protect_oar,
                    parallel_min_distance_mm=parallel_min_distance_mm,
                    parallel_angle_tolerance_deg=parallel_angle_tolerance_deg,
                    preview_callback=preview_callback,
                )
            except DoseInferenceDeadlineExceeded:
                logger.warning("[rl] Plan construction stopped at the DoseUNet deadline")
                set_outcome(
                    rl_status,
                    execution="interrupted",
                    stop_reason="dose_inference_deadline",
                )
                return
            except Exception:
                logger.exception("Plan construction failed")
                return
            if not constructed:
                return
            construction_score, construction_coverage = evaluate_plan_objective(
                constructed,
                radiation_volume,
                target_value,
                in_lowest_dose,
                out_highest_dose,
                DVH_rate,
            )
            construction_needles, construction_seeds = plan_cost_counts(constructed)
            logger.info(
                "[rl] construction incumbent: objective=%.4f coverage=%.4f needles=%d seeds=%d",
                construction_score, construction_coverage,
                construction_needles, construction_seeds,
            )
            if rl_status is not None:
                rl_status["construction_needles"] = int(construction_needles)
                rl_status["construction_seeds"] = int(construction_seeds)
                rl_status["construction_coverage"] = float(construction_coverage)
            if construction_score > best_reward:
                best_reward = construction_score
                best_plan = constructed
                _emit_preview(
                    best_plan, "rl_plan_construction", 0,
                    construction_coverage, construction_score,
                )
            _record_plan(construction_coverage, construction_score)

        greedy_enabled = rf_params.get("greedy_warm_start", True)
        if isinstance(greedy_enabled, str):
            greedy_enabled = greedy_enabled.strip().lower() not in {"0", "false", "no", "off"}
        if greedy_enabled:
            if construction_candidates and distance_map is not None:
                _construction_incumbent()
            else:
                _greedy_incumbent(best_group_idx, "rl_greedy_warm_start")

        # Baseline-informed initialization for the high-level policy: bias the
        # (group, anchor) logits toward the groups whose dense evaluation
        # already scores well, so early episodes explore promising anchors
        # instead of a uniform prior over hundreds of actions.
        if group_objectives and len(high_level_state_spaces) > 0:
            try:
                scores = np.array(
                    [group_objectives.get(g, 0.0) for g in range(len(target_level_traj))],
                    dtype=np.float64,
                )
                mean_score = float(scores.mean()) if scores.size else 0.0
                level = max(1, int(target_level))
                bias = torch.zeros(len(high_level_state_spaces), device=device)
                for flat_idx in range(len(high_level_state_spaces)):
                    group_of = int(np.searchsorted(env.cum_sizes, flat_idx, side="right") // level)
                    if len(scores):
                        group_of = min(group_of, len(scores) - 1)
                    else:
                        group_of = 0
                    bias[flat_idx] = 1.5 * (float(scores[group_of]) - mean_score)
                with torch.no_grad():
                    high_agent.policy.logits.bias.add_(bias)
            except Exception:
                logger.debug("Baseline-informed policy initialization failed", exc_info=True)

        if hierarchical_mode:
            high_loop_completed = True
            for _ in range(max_episodes // 2):
                if deadline is not None and time.monotonic() >= deadline:
                    logger.warning("[rl] Hierarchical RL episode loop reached its wall-clock budget")
                    high_loop_completed = False
                    _wall_clock_stop()
                    break
                try:
                    progressDialog.setValue(70)
                    progressDialog.setLabelText("Reinforcement Planning...")
                    slicer.app.processEvents()
                    
                    state = env.reset()
                    high_action = high_agent.select_action(state)
                    _status_counter("actions_taken")

                    low_reward, plan, cur_DVH_rate, mask, group_idx, low_level_state_space, low_env, low_agent = env.step(high_action, device=device)

                    high_agent.record_reward(low_reward)
                    high_agent.finish_episode()

                    plan_score, plan_coverage = evaluate_plan_objective(
                        plan,
                        radiation_volume,
                        target_value,
                        in_lowest_dose,
                        out_highest_dose,
                        DVH_rate,
                    )
                    if plan_score > best_reward:
                        best_plan = plan
                        best_group_idx = group_idx
                        best_low_level_state_space = low_level_state_space
                        best_low_env = low_env
                        best_low_agent = low_agent
                        best_reward = plan_score
                        logger.debug(
                            "[rl] improved hierarchical plan: objective=%.4f coverage=%.4f",
                            plan_score,
                            plan_coverage,
                        )
                        _emit_preview(
                            best_plan, "rl_trajectory_refinement", _,
                            plan_coverage, plan_score,
                        )

                    _record_plan(plan_coverage, plan_score)
                    _status_counter("high_level_episodes")
                    _status_counter("episodes_completed")
                    
                    low_agent.finish_episode()
                except DoseInferenceDeadlineExceeded:
                    logger.warning("[rl] Hierarchical RL stopped at the DoseUNet deadline")
                    high_loop_completed = False
                    set_outcome(
                        rl_status,
                        execution="interrupted",
                        stop_reason="dose_inference_deadline",
                    )
                    break
                except Exception:
                    logger.debug("Hierarchical RL episode failed", exc_info=True)
                    try:
                        low_agent.finish_episode()
                    except Exception:
                        pass
                    continue

            if greedy_enabled and best_group_idx is not None:
                _greedy_incumbent(best_group_idx, "rl_greedy_refinement")

            planned_directions = [np.array([0, 0, 1]) for _ in range(target_level)]
            best_cunsum = np.cumsum(range_length[best_group_idx * target_level:])
            best_traj = target_level_traj[best_group_idx]
            best_sub_state_space = low_level_state_spaces[best_group_idx]

            traj_cache = []
            for lv in range(target_level):
                slicer.app.processEvents()  
                traj = best_traj[lv][1]
                point = np.array(traj[0]).reshape(-1)
                direction = np.array(traj[1]).reshape(-1).astype(np.float64)
                direction /= np.linalg.norm(direction)
                max_idx = np.argmax(np.abs(direction))
                update_dir = direction / np.abs(direction[max_idx])
                world_p = utilizations.position_transform(dose_image, point)[0]
                traj_cache.append((best_traj[lv], point, direction, update_dir, world_p, best_sub_state_space[lv]))

            pos_cache = {}
            for lv, (_, point, _, update_dir, _, effective_range) in enumerate(traj_cache):
                slicer.app.processEvents()  
                try:
                    positions = env.candidate_world_positions[(best_group_idx, lv)]
                    lengths = best_sub_state_space[lv]
                    for idx, length in enumerate(lengths):
                        pos_cache[(lv, length)] = positions[idx]
                except Exception:
                    for length in effective_range:
                        img_position = point + update_dir * length
                        pos_cache[(lv, length)] = utilizations.position_transform(dose_image, img_position)[0]

            low_loop_completed = True
            for ep in range(max_episodes // 2):
                if deadline is not None and time.monotonic() >= deadline:
                    logger.warning("[rl] Low-level RL episode loop reached its wall-clock budget")
                    low_loop_completed = False
                    _wall_clock_stop()
                    break
                try:
                    progressDialog.setValue(80)
                    progressDialog.setLabelText("Reinforcement Planning...")
                    slicer.app.processEvents()
                    
                    planned_positions = [[] for _ in range(target_level)]
                    planned_seed_radiations = [[] for _ in range(target_level)]

                    cur_radiation = np.zeros_like(radiation_volume, dtype=np.float32)
                    cur_DVH_rate = 0.0
                    best_low_env.reset()
                    state = np.zeros(POLICY_STATE_DIM, dtype=np.float32)

                    while not best_low_env.done:
                        try:
                            if deadline is not None and time.monotonic() >= deadline:
                                best_low_env.done = True
                                low_loop_completed = False
                                _wall_clock_stop()
                                break
                            mask = []
                            slicer.app.processEvents()  
                            for lv in range(target_level):
                                _, _, _, update_dir, world_p, effective_range = traj_cache[lv]
                                lv_mask = np.ones(len(effective_range), dtype=bool)

                                if planned_positions[lv]:
                                    all_pos = np.array([pos_cache[(lv, x)] for x in effective_range])
                                    dists = np.linalg.norm(all_pos - world_p, axis=1)
                                    for planned_pos in planned_positions[lv]:
                                        dist = np.linalg.norm(planned_pos - world_p)
                                        start, end = dist - seed_info['length'], dist + seed_info['length']
                                        lv_mask[(dists > start) & (dists < end)] = False

                                mask.extend(lv_mask)

                            mask = np.array(mask, dtype=bool)
                            if mask.shape != best_low_env.used_mask.shape:
                                raise ValueError(
                                    "Best low-level action mask does not match its candidate space"
                                )
                            mask &= best_low_env.used_mask
                            if np.any(mask):
                                placed_total = sum(len(entry) for entry in planned_positions)
                                available_frac = float(np.count_nonzero(mask)) / max(1, mask.size)
                                state = np.array([
                                    min(1.5, float(cur_DVH_rate) / max(float(DVH_rate), 1e-6)),
                                    min(1.0, float(getattr(reward_calculator, "last_out_damage", 0.0) or 0.0)),
                                    placed_total / max(1.0, float(max_actions_per_episode or 1)),
                                    available_frac,
                                ], dtype=np.float32)
                                a = best_low_agent.select_action(state, mask=mask)
                                _status_counter("actions_taken")
                                best_low_env.step(a)
                                lv = np.searchsorted(best_cunsum, a, side="right") % target_level
                                traj, point, direction, update_dir, *_ = traj_cache[lv]

                                length = best_low_level_state_space[a]
                                img_position = point + update_dir * length
                                world_position = pos_cache[(lv, length)]

                                is_new_needle = not planned_positions[lv]
                                reward, cur_radiation, cur_DVH_rate, cur_seed_radiation = reward_calculator.forward(
                                    traj=traj,
                                    cur_radiation=cur_radiation,
                                    direction=direction,
                                    seed_point=img_position,
                                    protect_OAR=protect_oar,
                                    seed_count=placed_total + 1,
                                    needle_count=sum(1 for entry in planned_positions if entry) + (1 if is_new_needle else 0),
                                    is_new_needle=is_new_needle,
                                )

                                best_low_agent.record_reward(reward)
                                if cur_seed_radiation is None:
                                    continue
                                planned_positions[lv].append(world_position)
                                planned_seed_radiations[lv].append(cur_seed_radiation)
                                planned_directions[lv] = np.array(utilizations.direction_transform(dose_image, direction))[0]

                                if cur_DVH_rate >= DVH_rate:
                                    best_low_env.done = True
                            else:
                                if not planned_positions[0] and rl_status is not None:
                                    rl_status["no_action_observed"] = True
                                best_low_env.done = True
                        except DoseInferenceDeadlineExceeded:
                            logger.warning("[rl] Low-level RL stopped at the DoseUNet deadline")
                            low_loop_completed = False
                            set_outcome(
                                rl_status,
                                execution="interrupted",
                                stop_reason="dose_inference_deadline",
                            )
                            best_low_env.done = True
                            break
                        except Exception:
                            logger.debug("RL seed placement step failed", exc_info=True)
                            best_low_env.done = True

                    planned_res = []
                    for lv in range(target_level):
                        seeds = [[pos, planned_directions[lv]] for pos in planned_positions[lv]]
                        single_seed_radiations = planned_seed_radiations[lv]
                        trajectory_def = best_traj[lv][1]
                        planned_res.append([trajectory_def, seeds, single_seed_radiations])

                    plan_score, plan_coverage = evaluate_plan_objective(
                        planned_res,
                        radiation_volume,
                        target_value,
                        in_lowest_dose,
                        out_highest_dose,
                        DVH_rate,
                    )
                    if plan_score > best_reward:
                        best_reward = plan_score
                        best_plan = planned_res
                        logger.debug(
                            "[rl] improved low-level plan: objective=%.4f coverage=%.4f",
                            plan_score,
                            plan_coverage,
                        )
                        _emit_preview(
                            best_plan, "rl_seed_refinement", ep + 1,
                            plan_coverage, plan_score,
                        )

                    _record_plan(plan_coverage, plan_score)
                    _status_counter("low_level_episodes")
                    _status_counter("episodes_completed")

                    del cur_radiation
                    best_low_agent.finish_episode()
                except DoseInferenceDeadlineExceeded:
                    logger.warning("[rl] Low-level optimization stopped at the DoseUNet deadline")
                    low_loop_completed = False
                    set_outcome(
                        rl_status,
                        execution="interrupted",
                        stop_reason="dose_inference_deadline",
                    )
                    break
                except Exception:
                    logger.debug("Low-level RL optimization episode failed", exc_info=True)
                    try:
                        best_low_agent.finish_episode()
                    except Exception:
                        pass
                    continue

        else:
            flat_loop_completed = True
            for ep in range(max_episodes):
                if deadline is not None and time.monotonic() >= deadline:
                    logger.warning("[rl] Flat RL episode loop reached its wall-clock budget")
                    flat_loop_completed = False
                    _wall_clock_stop()
                    break
                try:
                    progressDialog.setValue(70)
                    progressDialog.setLabelText("Reinforcement Planning...")
                    slicer.app.processEvents()
                    
                    state = env.reset()
                    high_action = high_agent.select_action(state)
                    _status_counter("actions_taken")

                    low_reward, plan, cur_DVH_rate, mask, group_idx, low_level_state_space, low_env, low_agent = env.step(high_action, device=device)

                    high_agent.record_reward(low_reward)
                    high_agent.finish_episode()

                    plan_score, plan_coverage = evaluate_plan_objective(
                        plan,
                        radiation_volume,
                        target_value,
                        in_lowest_dose,
                        out_highest_dose,
                        DVH_rate,
                    )
                    if plan_score > best_reward:
                        best_reward = plan_score
                        best_plan = plan
                        logger.debug(
                            "[rl] improved flat plan: objective=%.4f coverage=%.4f",
                            plan_score,
                            plan_coverage,
                        )
                        _emit_preview(
                            best_plan, "rl_plan_refinement", ep + 1,
                            plan_coverage, plan_score,
                        )
                    _record_plan(plan_coverage, plan_score)
                    _status_counter("high_level_episodes")
                    _status_counter("episodes_completed")
                    low_agent.finish_episode()
                except DoseInferenceDeadlineExceeded:
                    logger.warning("[rl] Flat RL stopped at the DoseUNet deadline")
                    flat_loop_completed = False
                    set_outcome(
                        rl_status,
                        execution="interrupted",
                        stop_reason="dose_inference_deadline",
                    )
                    break
                except Exception:
                    logger.debug("Flat RL optimization episode failed", exc_info=True)
                    try:
                        low_agent.finish_episode()
                    except Exception:
                        pass
                    continue
        logger.info(
            "[rl] seed-dose cache: %d hits, %d model evaluations, %.2fs uncached inference",
            reward_calculator.cache_hits,
            reward_calculator.cache_misses,
            reward_calculator.model_inference_seconds,
        )
        if rl_status is not None:
            rl_status["dose_cache_hits"] = int(
                getattr(reward_calculator, "cache_hits", 0) or 0
            )
            rl_status["dose_cache_misses"] = int(
                getattr(reward_calculator, "cache_misses", 0) or 0
            )
            if rl_status.get("_stop_reason") is None:
                if (rl_status.get("best_coverage", 0.0) or 0.0) >= float(DVH_rate):
                    set_outcome(
                        rl_status,
                        execution="completed",
                        stop_reason="target_reached",
                    )
                else:
                    if rf_params.get("hierarchical_optimization"):
                        loops_completed = bool(
                            high_loop_completed and low_loop_completed
                        )
                    else:
                        loops_completed = bool(flat_loop_completed)
                    set_outcome(
                        rl_status,
                        execution="completed",
                        stop_reason=(
                            "episode_budget_exhausted"
                            if loops_completed and int(rf_params.get("max_episodes", 0) or 0) > 0
                            else (
                                "no_available_action"
                                if rl_status.get("no_action_observed")
                                else "completed_without_target"
                            )
                        ),
                    )
        _emit_preview(
            best_plan,
            "rl_best_plan",
            int((rl_status or {}).get("episodes_completed") or 0),
            float((rl_status or {}).get("best_coverage") or 0.0),
            best_reward,
            force=True,
        )
        return best_plan, best_reward
    except DoseInferenceDeadlineExceeded:
        logger.warning("[rl] Reinforcement planning reached the DoseUNet deadline")
        set_outcome(
            rl_status,
            execution="interrupted",
            stop_reason="dose_inference_deadline",
        )
        if rl_status is not None:
            rl_status["dose_cache_hits"] = int(
                getattr(locals().get("reward_calculator"), "cache_hits", 0) or 0
            )
            rl_status["dose_cache_misses"] = int(
                getattr(locals().get("reward_calculator"), "cache_misses", 0) or 0
            )
        _emit_preview(
            best_plan, "rl_interrupted_best", 0,
            float((rl_status or {}).get("best_coverage") or 0.0),
            best_reward, force=True,
        )
        return ([] if best_plan is None else best_plan), best_reward
    except Exception:
        logger.exception("Reinforcement planning failed")
        set_outcome(
            rl_status,
            execution="failed",
            stop_reason="internal_exception",
        )
        if best_plan is not None:
            return best_plan, best_reward
        return [], -np.inf
