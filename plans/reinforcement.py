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
from .reward_metrics import normalized_oar_damage
try:
    from . import _reward_core
except ImportError:
    _reward_core = None

logger = logging.getLogger(__name__)


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



def percentile_value_in_mask(image: np.ndarray, mask: np.ndarray, ratio: float = 0.1):
    """
    Compute the pixel value threshold corresponding to the lowest `ratio` proportion
    (e.g., bottom 10%) of pixel intensities within a masked region.
    
    Args:
        image (np.ndarray): Grayscale image.
        mask (np.ndarray): Binary mask (same shape as image).
        ratio (float): Ratio of lowest values to consider (e.g., 0.1 for 10%).
    
    Returns:
        float: The pixel value at the cutoff (bottom ratio).
    """
    # Extract pixel values in the mask region
    masked_values = image[mask > 0]
    
    if masked_values.size == 0:
        raise ValueError("Mask region is empty.")
    
    # Sort values from large to small
    sorted_values = np.sort(masked_values)[::-1]
    
    # Get the index corresponding to the bottom `ratio` of sorted values
    index = int(len(sorted_values) * (1 - ratio))
    index = np.clip(index, 0, len(sorted_values) - 1)
    
    return sorted_values[index]



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
    def forward(self,
                traj: list,
                cur_radiation: np.ndarray,
                direction: np.ndarray,
                seed_point: np.ndarray,
                protect_OAR: bool = True):
        """
        Compute reward for placing one seed.
        Returns: reward, updated_dose, DVH_rate, seed_dose_map
        """
        try:
            seed_point_int=np.array(seed_point).astype(int)
            key = tuple(seed_point_int)

            cur_seed_radiation = self.seed_cache.get(key, None)
            if cur_seed_radiation is not None:
                self.cache_hits += 1

            if cur_seed_radiation is None:
                for cached_seed, cached_dose in zip(traj[2], traj[3]):
                    if np.linalg.norm(np.asarray(cached_seed[0]).ravel() - seed_point) < 1e-3:
                        cur_seed_radiation = cached_dose
                        self.seed_cache[key] = cur_seed_radiation.copy()
                        self.cache_hits += 1
                        break

            if cur_seed_radiation is None:
                self.cache_misses += 1
                inference_started = time.perf_counter()
                cur_seed_radiation = utilizations.single_seed_dose_calculation_dl(
                    seed_point_int.reshape(-1),
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
                self.seed_cache[key] = cur_seed_radiation.copy()

        # 4.  accumulate dose (in-place to save memory)
        # Ensure cur_radiation is float32 to match cur_seed_radiation
            if cur_radiation.dtype != cur_seed_radiation.dtype:
                cur_radiation = cur_radiation.astype(cur_seed_radiation.dtype)
            np.add(cur_radiation, cur_seed_radiation, out=cur_radiation)

            dose_flat = np.ascontiguousarray(cur_radiation.ravel(), dtype=np.float64)
            target_idx_c = np.ascontiguousarray(self.target_idx, dtype=np.int32)
            non_target_idx_c = np.ascontiguousarray(self.non_target_idx, dtype=np.int32)

            if not protect_OAR:
                _fn = _reward_core._dvh_oar_jit if _reward_core is not None else _dvh_oar_jit_fallback
                cur_DVH_rate, out_damage = _fn(
                    dose_flat, target_idx_c, non_target_idx_c,
                    float(self.in_lowest_dose), float(self.out_highest_dose),
                    count_out=False
                )
                reward = cur_DVH_rate
            else:
                _fn = _reward_core._dvh_oar_jit if _reward_core is not None else _dvh_oar_jit_fallback
                cur_DVH_rate, out_damage = _fn(
                    dose_flat, target_idx_c, non_target_idx_c,
                    float(self.in_lowest_dose), float(self.out_highest_dose),
                    count_out=True
                )
                reward = min(cur_DVH_rate, self.DVH_rate) + \
                         ((cur_DVH_rate - self.DVH_rate) >= 0) * (1.0 - out_damage)

            return reward, cur_radiation, cur_DVH_rate, cur_seed_radiation
        except DoseInferenceDeadlineExceeded:
            # The caller owns the episode boundary and will return its best
            # valid plan. Do not convert an expired budget into fake zero dose.
            raise
        except Exception as e:
            logger.exception("Seed-placement reward calculation failed: %s", e)
            # A single-seed dose map has the same full-volume shape as the
            # cumulative radiation array; a zero map preserves that contract.
            return 0.0, cur_radiation, 0.0, np.zeros_like(cur_radiation)


# ==========================================================
# 2.  Policy Network
# ==========================================================
class PolicyNet(nn.Module):
    """Simple MLP policy for discrete actions."""
    def __init__(self, n_actions, hidden=128):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(1, hidden), nn.ReLU(),
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
    def __init__(self, n_actions, lr=1e-2, gamma=0.99, device="cpu"):
        self.device = torch.device(device)
        self.policy = PolicyNet(n_actions).to(self.device)
        self.optimizer = optim.Adam(self.policy.parameters(), lr=lr)
        self.gamma = gamma
        self.log_probs = []
        self.rewards = []

    # ------------------------------------------------------
    def select_action(self, state, mask=None):
        """Return action index (int) and store log_prob."""
        # state is small (shape (1,)) -- keep as float32
        state_array = np.array(state, dtype=np.float32)
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
        self.cur_radiation = np.zeros_like(radiation_volume)
        self.reward_calculator = reward_calculator
        self.max_actions_per_episode = max_actions_per_episode
        self.deadline = deadline
        
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

        reward, self.cur_radiation, cur_DVH_rate, cur_seed_radiation = self.reward_calculator.forward(
            traj=self.target_level_traj[self.group_idx][lv],
            cur_radiation=self.cur_radiation.copy(),
            direction=direction,
            seed_point=img_position,
            protect_OAR=self.protect_OAR
        )

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
    def step(self, action, device="cpu"):
        """
        Execute high-level action, then run full low-level episode.
        Returns:
            total_reward (float), plan_tuple (high_action, planned_positions)
        """
        try:
            self.low_level_state_space = self.generate_low_level_state_space(action)
            low_env = LowLevelEnv(
                self.low_level_state_space,
                max_steps=self.max_actions_per_episode,
            )
            low_agent = REINFORCE(n_actions=len(self.low_level_state_space), device=device)

            state = low_env.reset()

            # Keep the initial high-level seed's coverage.  Dropping this
            # value made a one-seed valid plan look like V100=0 whenever the
            # low-level action space was exhausted immediately.
            total_reward, cur_DVH_rate = self.update_planned_position(action, high_level=True)

            mask = None
            while not low_env.done:
                try:
                    if self.deadline is not None and time.monotonic() >= self.deadline:
                        low_env.done = True
                        break
                    slicer.app.processEvents()
                    mask = self.generate_mask(low_env.used_mask)
                    if mask.any():
                        a = low_agent.select_action(state, mask=mask)
                        state, _, _ = low_env.step(a)
                        r, cur_DVH_rate = self.update_planned_position(a, high_level=False)
                        low_agent.record_reward(r)
                        total_reward += r
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
            return -np.inf, planned_res, 0.0, None, self.group_idx, self.low_level_state_space if hasattr(self, 'low_level_state_space') else [], LowLevelEnv([]), REINFORCE(1)



def randomly_flip_false(mask: np.ndarray, flip_ratio: float = 0.5, seed: int = None):
    """
    Randomly flip a fraction of False values in a boolean mask to True.

    Parameters
    ----------
    mask : np.ndarray
        Boolean array of any shape.
    flip_ratio : float
        Fraction of False values to flip to True (0 < flip_ratio <= 1).
    seed : int, optional
        Random seed for reproducibility.

    Returns
    -------
    np.ndarray
        New boolean array with the specified fraction of False flipped to True.
    """
    if seed is not None:
        np.random.seed(seed)
    
    mask = mask.copy()  # avoid modifying original
    false_idx = np.where(mask == False)  # get all False indices
    n_flip = int(len(false_idx[0]) * flip_ratio)
    
    if n_flip > 0:
        flip_idx = np.random.choice(len(false_idx[0]), size=n_flip, replace=False)
        mask[tuple(idx[flip_idx] for idx in false_idx)] = True
    
    return mask


def DVH2Rewards(plan_res, radiation_volume, target_value, out_highest_dose, cur_DVH_rate, DVH_rate):
    """
    Compute DVH rate and reward for a given plan result.
    """
    # Accumulate total radiation from all seeds
    total_radiation = np.zeros_like(radiation_volume).astype(float)
    for _, _, single_seed_radiations in plan_res:
        for single_seed_radiation in single_seed_radiations:
            total_radiation += single_seed_radiation

    # Compute DVH rate
    # mask_volume is 0.0/1.0 (float), use == 0 to find non-target voxels
    mask_volume = (radiation_volume == target_value).astype(float)
    non_target_idx = np.where(mask_volume == 0)
    target_idx = np.where(mask_volume == 1)

    non_target_voxels = total_radiation[non_target_idx]
    exceed_count = np.count_nonzero(non_target_voxels > out_highest_dose)

    out_damage = normalized_oar_damage(exceed_count, len(target_idx[0]))

    reward = min(cur_DVH_rate, DVH_rate) + ((cur_DVH_rate - DVH_rate) >= 0) * (1.0 - out_damage)

    return reward


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
    objective = min(coverage, float(DVH_rate)) + (
        (coverage >= float(DVH_rate)) * (1.0 - out_damage)
    )
    return float(objective), coverage


def generate_baseline_state_space(low_level_state_spaces, level, idx):
    merged = []
    for lv in range(level):
        merged.extend(low_level_state_spaces[idx][lv])
    return merged



def generate_plan_res(dose_image, elem):
    planned_res = []
    for _, traj, seeds, single_seed_radiations, _ in elem:
        slicer.app.processEvents()
        direction = utilizations.direction_transform(dose_image, np.array(traj[1]).reshape(-1))
        world_seeds = []
        for _, seed in enumerate(seeds):
            world_seeds.append([utilizations.position_transform(dose_image, seed[0]), direction])
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
        max_actions_per_episode=None):
    """
    Hierarchical reinforcement learning driver for a single patient case.
    Logic preserved; internal calls use optimized env and caches.
    """
    # Initialize the recovery state before any model access so the exception
    # path can always return a valid result instead of masking the root error.
    best_plan = None
    best_reward = -np.inf
    try:
        device = next(dose_cal_model.parameters()).device

        high_agent = REINFORCE(
            n_actions=len(high_level_state_spaces),
            lr=rf_params['lr'],
            gamma=rf_params['gamma'],
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
            seed_info, reward_calculator, DVH_rate, rf_params['segmented_rewards'],
            max_actions_per_episode=max_actions_per_episode,
            deadline=deadline,
        )

        best_group_idx = None
        best_low_level_state_space = None
        best_low_env = None
        best_low_agent = None

        for idx, elem in enumerate(target_level_traj):
            if deadline is not None and time.monotonic() >= deadline:
                logger.warning("[rl] Baseline trajectory scoring reached its wall-clock budget")
                break
            try:
                progressDialog.setValue(65)
                progressDialog.setLabelText("Learning-based Planning...")
                slicer.app.processEvents()
                
                trajs_radiations = np.zeros_like(radiation_volume, dtype=np.float32)
                for _, traj, _, _, cur_seeds_radiations in elem:
                    trajs_radiations += cur_seeds_radiations
                if rf_params['segmented_rewards']:
                    target_sum = np.sum(trajs_radiations * reward_calculator.mask_volume > in_lowest_dose)
                    cur_DVH_rate = target_sum / reward_calculator.target_v
                    non_target_sum = np.count_nonzero(
                        (trajs_radiations * reward_calculator.non_target_mask > out_highest_dose)
                    )
                    cur_out_damage = normalized_oar_damage(
                        non_target_sum, reward_calculator.target_v
                    )
                    cur_reward = min(cur_DVH_rate, DVH_rate) + (
                        (cur_DVH_rate >= DVH_rate) * (1.0 - cur_out_damage)
                    )
                else:
                    target_sum = np.sum(trajs_radiations * reward_calculator.mask_volume > in_lowest_dose)
                    cur_reward = cur_DVH_rate = target_sum / reward_calculator.target_v

                if cur_reward > best_reward:
                    best_reward = cur_reward
                    best_plan = generate_plan_res(dose_image, elem)
                    best_group_idx = idx
                    best_low_level_state_space = generate_baseline_state_space(
                        low_level_state_spaces, target_level, idx
                    )
                del trajs_radiations
            except Exception:
                logger.debug("Initial RL trajectory evaluation failed", exc_info=True)
                continue

        # Guard: if no valid trajectory was found, return early
        if best_low_level_state_space is None or best_plan is None:
            return [], -np.inf

        best_low_env = LowLevelEnv(
            best_low_level_state_space,
            max_steps=max_actions_per_episode,
        )
        best_low_agent = REINFORCE(n_actions=len(best_low_level_state_space), device=device)
        
        if rf_params['hierarchical_optimization']:
            for _ in range(rf_params['max_episodes'] // 2):
                if deadline is not None and time.monotonic() >= deadline:
                    logger.warning("[rl] Hierarchical RL episode loop reached its wall-clock budget")
                    break
                try:
                    progressDialog.setValue(70)
                    progressDialog.setLabelText("Reinforcement Planning...")
                    slicer.app.processEvents()
                    
                    state = env.reset()
                    high_action = high_agent.select_action(state)

                    low_reward, plan, cur_DVH_rate, mask, group_idx, low_level_state_space, low_env, low_agent = env.step(high_action, device=device)

                    high_agent.record_reward(low_reward)
                    high_agent.finish_episode()

                    plan_objective, plan_coverage = evaluate_plan_objective(
                        plan,
                        radiation_volume,
                        target_value,
                        in_lowest_dose,
                        out_highest_dose,
                        DVH_rate,
                    )
                    if plan_objective > best_reward:
                        best_plan = plan
                        best_group_idx = group_idx
                        best_low_level_state_space = low_level_state_space
                        best_low_env = low_env
                        best_low_agent = low_agent
                        best_reward = plan_objective
                        logger.debug(
                            "[rl] improved hierarchical plan: objective=%.4f coverage=%.4f",
                            plan_objective,
                            plan_coverage,
                        )
                    
                    low_agent.finish_episode()
                except DoseInferenceDeadlineExceeded:
                    logger.warning("[rl] Hierarchical RL stopped at the DoseUNet deadline")
                    break
                except Exception:
                    logger.debug("Hierarchical RL episode failed", exc_info=True)
                    try:
                        low_agent.finish_episode()
                    except Exception:
                        pass
                    continue

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

            for ep in range(rf_params['max_episodes'] // 2):
                if deadline is not None and time.monotonic() >= deadline:
                    logger.warning("[rl] Low-level RL episode loop reached its wall-clock budget")
                    break
                try:
                    progressDialog.setValue(80)
                    progressDialog.setLabelText("Reinforcement Planning...")
                    slicer.app.processEvents()
                    
                    planned_positions = [[] for _ in range(target_level)]
                    planned_seed_radiations = [[] for _ in range(target_level)]

                    cur_radiation = np.zeros_like(radiation_volume)
                    state = best_low_env.reset()

                    while not best_low_env.done:
                        try:
                            if deadline is not None and time.monotonic() >= deadline:
                                best_low_env.done = True
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
                                a = best_low_agent.select_action(state, mask=mask)
                                state, _, _ = best_low_env.step(a)
                                lv = np.searchsorted(best_cunsum, a, side="right") % target_level
                                traj, point, direction, update_dir, *_ = traj_cache[lv]

                                length = best_low_level_state_space[a]
                                img_position = point + update_dir * length
                                world_position = pos_cache[(lv, length)]

                                reward, cur_radiation, cur_DVH_rate, cur_seed_radiation = reward_calculator.forward(
                                    traj=traj,
                                    cur_radiation=cur_radiation,
                                    direction=direction,
                                    seed_point=img_position,
                                    protect_OAR=rf_params['segmented_rewards']
                                )

                                best_low_agent.record_reward(reward)
                                planned_positions[lv].append(world_position)
                                planned_seed_radiations[lv].append(cur_seed_radiation)
                                planned_directions[lv] = np.array(utilizations.direction_transform(dose_image, direction))[0]

                                if cur_DVH_rate >= DVH_rate:
                                    best_low_env.done = True
                            else:
                                best_low_env.done = True
                        except DoseInferenceDeadlineExceeded:
                            logger.warning("[rl] Low-level RL stopped at the DoseUNet deadline")
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

                    plan_objective, plan_coverage = evaluate_plan_objective(
                        planned_res,
                        radiation_volume,
                        target_value,
                        in_lowest_dose,
                        out_highest_dose,
                        DVH_rate,
                    )
                    if plan_objective > best_reward:
                        best_reward = plan_objective
                        best_plan = planned_res
                        logger.debug(
                            "[rl] improved low-level plan: objective=%.4f coverage=%.4f",
                            plan_objective,
                            plan_coverage,
                        )

                    del cur_radiation
                    best_low_agent.finish_episode()
                except DoseInferenceDeadlineExceeded:
                    logger.warning("[rl] Low-level optimization stopped at the DoseUNet deadline")
                    break
                except Exception:
                    logger.debug("Low-level RL optimization episode failed", exc_info=True)
                    try:
                        best_low_agent.finish_episode()
                    except Exception:
                        pass
                    continue

        else:
            for ep in range(rf_params['max_episodes']):
                if deadline is not None and time.monotonic() >= deadline:
                    logger.warning("[rl] Flat RL episode loop reached its wall-clock budget")
                    break
                try:
                    progressDialog.setValue(70)
                    progressDialog.setLabelText("Reinforcement Planning...")
                    slicer.app.processEvents()
                    
                    state = env.reset()
                    high_action = high_agent.select_action(state)

                    low_reward, plan, cur_DVH_rate, mask, group_idx, low_level_state_space, low_env, low_agent = env.step(high_action, device=device)

                    high_agent.record_reward(low_reward)
                    high_agent.finish_episode()

                    plan_objective, plan_coverage = evaluate_plan_objective(
                        plan,
                        radiation_volume,
                        target_value,
                        in_lowest_dose,
                        out_highest_dose,
                        DVH_rate,
                    )
                    if plan_objective > best_reward:
                        best_reward = plan_objective
                        best_plan = plan
                        logger.debug(
                            "[rl] improved flat plan: objective=%.4f coverage=%.4f",
                            plan_objective,
                            plan_coverage,
                        )
                    low_agent.finish_episode()
                except DoseInferenceDeadlineExceeded:
                    logger.warning("[rl] Flat RL stopped at the DoseUNet deadline")
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
        return best_plan, best_reward
    except DoseInferenceDeadlineExceeded:
        logger.warning("[rl] Reinforcement planning reached the DoseUNet deadline")
        return ([] if best_plan is None else best_plan), best_reward
    except Exception:
        logger.exception("Reinforcement planning failed")
        if best_plan is not None:
            return best_plan, best_reward
        return [], -np.inf
