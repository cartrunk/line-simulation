"""
Citrus Production Line Simulator
Demand-driven, accumulator-controlled mass-flow system
"""

from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Optional
from enum import Enum
import json
import random


# ============================================================================
# ENUMS & TYPES
# ============================================================================

class FruitGrade(Enum):
    PACK = "pack"
    RECYCLE = "recycle"
    JUICE = "juice"


class ControlMode(Enum):
    AUTO = "auto"
    MANUAL = "manual"


@dataclass
class Fruit:
    """Individual fruit after singulation"""
    weight_lbs: float
    grade: FruitGrade
    lane_id: int
    created_at_sec: float


@dataclass
class BulkFlowComponent:
    """Generic mass-flow component (rate-based)"""
    name: str
    max_rate_lbs_per_sec: float
    yield_loss_pct: float = 0.0  # Mass lost in component
    delay_sec: float = 0.0  # Time in system
    
    def process(self, input_mass_lbs: float, dt_sec: float) -> float:
        """Process mass through component, return output mass"""
        available = input_mass_lbs / dt_sec if dt_sec > 0 else 0
        output_rate = min(available, self.max_rate_lbs_per_sec)
        yield_ratio = 1.0 - (self.yield_loss_pct / 100.0)
        return output_rate * dt_sec * yield_ratio


@dataclass
class Lane:
    """10 parallel singulator lanes with cup buffer"""
    lane_id: int
    buffer_capacity: int = 720  # fruit count
    scan_time_sec: float = 1.0
    
    buffer: List[Fruit] = field(default_factory=list)
    
    def add_fruit(self, fruit: Fruit) -> None:
        """Add fruit to buffer (if space)"""
        if len(self.buffer) < self.buffer_capacity:
            self.buffer.append(fruit)
    
    def scan_and_classify(self, dt_sec: float) -> Tuple[List[Fruit], float]:
        """
        Scan buffered fruit after dwell time.
        Returns: (classified fruits, recycle_mass_lbs)
        """
        classified = []
        recycle_mass = 0.0
        
        for fruit in self.buffer:
            classified.append(fruit)
            if fruit.grade == FruitGrade.RECYCLE:
                recycle_mass += fruit.weight_lbs
        
        self.buffer.clear()
        return classified, recycle_mass
    
    def utilization_pct(self) -> float:
        """Current buffer fill %"""
        return 100.0 * len(self.buffer) / self.buffer_capacity


@dataclass
class Accumulator:
    """4 independent buffers feeding PDGs"""
    accumulator_id: int
    capacity_lbs: float = 3600.0
    
    current_fill_lbs: float = 0.0
    
    def fill(self, mass_lbs: float) -> None:
        """Add mass up to capacity"""
        self.current_fill_lbs = min(
            self.current_fill_lbs + mass_lbs,
            self.capacity_lbs
        )
    
    def draw(self, demand_lbs: float) -> float:
        """Remove mass (up to available), return amount drawn"""
        drawn = min(demand_lbs, self.current_fill_lbs)
        self.current_fill_lbs -= drawn
        return drawn
    
    def fill_pct(self) -> float:
        """Current fill percentage"""
        return 100.0 * self.current_fill_lbs / self.capacity_lbs


@dataclass
class Bagger:
    """Individual bagger (consumes bags/min at fixed size)"""
    bagger_id: int
    pdg_id: int
    bag_size_lbs: float
    
    max_speed_bags_per_min: float = 30.0
    manual_speed_pct: float = 100.0
    
    active: bool = True
    bags_completed: int = 0
    partial_bag_lbs: float = 0.0  # Tracks sub-bag accumulation

    def demand_lbs_per_sec(self) -> float:
        """Current demand based on speed"""
        if not self.active:
            return 0.0

        bags_per_sec = (self.max_speed_bags_per_min / 60.0) * \
                       (self.manual_speed_pct / 100.0)
        return bags_per_sec * self.bag_size_lbs

    def produce(self, available_mass_lbs: float, dt_sec: float) -> float:
        """Produce bags from available mass, return mass consumed"""
        demand = self.demand_lbs_per_sec() * dt_sec
        consumed = min(demand, available_mass_lbs)

        if self.bag_size_lbs > 0:
            self.partial_bag_lbs += consumed
            bags_produced = int(self.partial_bag_lbs / self.bag_size_lbs)
            self.partial_bag_lbs -= bags_produced * self.bag_size_lbs
            self.bags_completed += bags_produced

        return consumed


@dataclass
class PDG:
    """Packing Density Group (feeds 2 baggers)"""
    pdg_id: int
    accumulator: Accumulator
    baggers: List[Bagger]
    
    def demand_lbs_per_sec(self) -> float:
        """Total demand from both baggers"""
        return sum(b.demand_lbs_per_sec() for b in self.baggers)
    
    def produce(self, upstream_mass_lbs: float, dt_sec: float) -> Tuple[float, float]:
        """
        Draw from accumulator, then upstream.
        Returns: (mass_consumed, mass_from_upstream)
        """
        total_demand = self.demand_lbs_per_sec() * dt_sec
        
        # Try accumulator first
        from_acc = self.accumulator.draw(total_demand)
        remaining_demand = total_demand - from_acc
        
        # Direct from upstream
        from_upstream = min(remaining_demand, upstream_mass_lbs)
        
        # Distribute to baggers proportionally
        total_available = from_acc + from_upstream
        remaining = total_available
        for bagger in self.baggers:
            bagger_share = min(bagger.demand_lbs_per_sec() * dt_sec, remaining)
            bagger.produce(bagger_share, dt_sec)
            remaining -= bagger_share
        
        return from_acc + from_upstream, from_upstream


# ============================================================================
# MAIN SIMULATOR
# ============================================================================

class ProductionLineSimulator:
    """Master simulator: bins → baggers → cases → pallets"""
    
    def __init__(self):
        # Time tracking
        self.current_time_sec = 0.0
        self.dt_sec = 0.1
        
        # Control mode
        self.control_mode = ControlMode.AUTO
        
        # Bins (source)
        self.active_bin: Optional[Bin] = None
        self.bins_completed = 0
        self.bin_dump_rate_lbs_per_sec = 50.0
        self.manual_bin_speed_pct = 100.0
        self.auto_bin_enabled = True  # Auto-load next bin when current is consumed
        self.bin_weight_min = 600.0
        self.bin_weight_max = 900.0
        
        # Bulk flow components
        self.metering_belt = BulkFlowComponent(
            "Metering Belt", max_rate_lbs_per_sec=50.0
        )
        self.unstacking = BulkFlowComponent(
            "Unstacking", max_rate_lbs_per_sec=60.0
        )
        self.grade_table = BulkFlowComponent(
            "Grade Table", max_rate_lbs_per_sec=100.0, yield_loss_pct=15.0
        )
        self.wash_dry_wax = BulkFlowComponent(
            "Wash/Dry/Wax", max_rate_lbs_per_sec=80.0, yield_loss_pct=5.0
        )
        
        # Singulator (mass → discrete fruit)
        self.num_lanes = 10
        self.lanes: List[Lane] = [Lane(i) for i in range(self.num_lanes)]
        self.fruit_per_lane_per_sec = 5.0  # Base rate
        self.recycle_buffer_mass_lbs = 0.0
        
        # Camera classification
        self.pack_rate = 0.80  # % → pack
        self.recycle_rate = 0.10  # % → recycle
        self.juice_rate = 0.10  # % → juice
        
        # Fruit weight
        self.fruit_weight_lbs = 0.21
        
        # Accumulators (4 total, feeding 4 PDGs)
        self.accumulators = [
            Accumulator(i) for i in range(4)
        ]
        
        # PDGs & Baggers
        self.pdgs: List[PDG] = []
        self._init_pdgs_and_baggers()
        
        # Downstream aggregation
        self.case_size_lbs = 30.0
        self.pallet_size_cases = 60
        self.total_lbs_produced = 0.0
        self.cases_completed = 0
        self.pallets_completed = 0
        
        # Metrics
        self.bin_mass_history: List[Tuple[float, float]] = []  # (time, mass dumped)
        self.upstream_speed_multiplier = 1.0
        
        # Streams
        self.juice_lbs = 0.0
        self.pack_lbs = 0.0
        self.recycle_lbs = 0.0
    
    def _init_pdgs_and_baggers(self) -> None:
        """Initialize 4 PDGs, each with 2 baggers"""
        bag_sizes = [1.0, 2.0, 3.0, 5.0]
        
        for pdg_id in range(4):
            acc = self.accumulators[pdg_id]
            baggers = [
                Bagger(2*pdg_id, pdg_id, bag_sizes[pdg_id]),
                Bagger(2*pdg_id + 1, pdg_id, bag_sizes[pdg_id])
            ]
            pdg = PDG(pdg_id, acc, baggers)
            self.pdgs.append(pdg)
    
    # ========================================================================
    # CONTROL LOOP
    # ========================================================================
    
    def compute_upstream_speed_multiplier(self) -> float:
        """
        AUTO mode: compute multiplier from accumulator fill levels.
        Tunable thresholds.
        """
        avg_fill_pct = sum(a.fill_pct() for a in self.accumulators) / len(self.accumulators)
        
        if avg_fill_pct < 20:
            return 1.0
        elif avg_fill_pct < 50:
            return 0.8
        elif avg_fill_pct < 80:
            return 0.5
        else:
            return 0.0
    
    def update_control_signal(self) -> None:
        """Update upstream speed based on mode"""
        if self.control_mode == ControlMode.AUTO:
            self.upstream_speed_multiplier = self.compute_upstream_speed_multiplier()
    
    # ========================================================================
    # SIMULATION STEP
    # ========================================================================
    
    def step(self, dt_sec: float) -> None:
        """Execute one simulation timestep"""
        self.dt_sec = dt_sec
        
        # 1. Dump bin mass
        bin_mass_dumped = self._dump_bin(dt_sec)
        
        # 2. Propagate through bulk flow
        metering_output = self.metering_belt.process(bin_mass_dumped, dt_sec)
        unstacking_output = self.unstacking.process(metering_output, dt_sec)
        grade_table_output = self.grade_table.process(unstacking_output, dt_sec)
        wash_output = self.wash_dry_wax.process(grade_table_output, dt_sec)
        
        # 3. Singulator: mass → fruit, plus recycle loop
        singulator_input = wash_output + self.recycle_buffer_mass_lbs
        singulator_output_mass, fruits = self._singulate(singulator_input, dt_sec)
        self.recycle_buffer_mass_lbs = 0.0
        
        # 4. Lane buffers & classification, route to accumulators
        recycle_mass, classified_fruits = self._process_lanes(fruits, dt_sec)
        self.recycle_buffer_mass_lbs = recycle_mass

        # 5. Route classified pack fruit to accumulators
        self._route_fruits_to_accumulators(classified_fruits)
        
        # 6. PDGs consume from accumulators
        self._pdg_production(singulator_output_mass, dt_sec)
        
        # 7. Update control signal
        self.update_control_signal()
        
        # 8. Increment time
        self.current_time_sec += dt_sec
    
    def _dump_bin(self, dt_sec: float) -> float:
        """Dump active bin at rate, return mass dumped. Auto-loads next bin when empty."""
        if self.active_bin is None:
            if self.auto_bin_enabled:
                weight = random.uniform(self.bin_weight_min, self.bin_weight_max)
                self.active_bin = Bin(weight)
            else:
                return 0.0

        dump_rate = self.bin_dump_rate_lbs_per_sec * \
                    (self.manual_bin_speed_pct / 100.0) * \
                    self.upstream_speed_multiplier

        mass_dumped = min(
            dump_rate * dt_sec,
            self.active_bin.remaining_weight_lbs
        )

        self.active_bin.remaining_weight_lbs -= mass_dumped

        if self.active_bin.remaining_weight_lbs <= 0:
            self.bins_completed += 1
            self.active_bin = None

        self.bin_mass_history.append((self.current_time_sec, mass_dumped))
        return mass_dumped
    
    def _singulate(self, input_mass_lbs: float, dt_sec: float) -> Tuple[float, List[Fruit]]:
        """Convert mass to discrete fruit, distribute across lanes"""
        # Apply upstream speed to singulator
        singulator_input = input_mass_lbs * self.upstream_speed_multiplier
        
        # Max fruit/sec = lanes × fruit_per_lane_sec
        max_fruit_rate = self.num_lanes * self.fruit_per_lane_per_sec
        input_fruit_rate = singulator_input / self.fruit_weight_lbs
        actual_fruit_rate = min(input_fruit_rate, max_fruit_rate)
        
        num_fruits = int(actual_fruit_rate * dt_sec)
        output_mass = num_fruits * self.fruit_weight_lbs
        
        # Create fruit objects, assign evenly to lanes
        fruits = []
        for i in range(num_fruits):
            lane_id = i % self.num_lanes
            fruit = Fruit(
                weight_lbs=self.fruit_weight_lbs,
                grade=FruitGrade.PACK,  # Assigned later
                lane_id=lane_id,
                created_at_sec=self.current_time_sec
            )
            fruits.append(fruit)
            self.lanes[lane_id].add_fruit(fruit)
        
        return output_mass, fruits
    
    def _process_lanes(self, fruits: List[Fruit], dt_sec: float) -> Tuple[float, List[Fruit]]:
        """Scan lanes, classify fruit, return (recycle_mass, classified_fruits)"""
        recycle_mass = 0.0
        classified_fruits = []

        for lane in self.lanes:
            classified, lane_recycle = lane.scan_and_classify(dt_sec)
            classified_fruits.extend(classified)
            recycle_mass += lane_recycle

        # Assign grades (simplified: classify based on rate)
        for i, fruit in enumerate(classified_fruits):
            rand_val = (i * 0.618) % 1.0  # Golden ratio quasi-random

            if rand_val < self.pack_rate:
                fruit.grade = FruitGrade.PACK
            elif rand_val < self.pack_rate + self.recycle_rate:
                fruit.grade = FruitGrade.RECYCLE
                recycle_mass += fruit.weight_lbs
            else:
                fruit.grade = FruitGrade.JUICE

        return recycle_mass, classified_fruits

    def _route_fruits_to_accumulators(self, classified_fruits: List[Fruit]) -> None:
        """Route classified fruit to accumulators or juice"""
        for fruit in classified_fruits:
            if fruit.grade == FruitGrade.PACK:
                acc_id = fruit.lane_id % len(self.accumulators)
                self.accumulators[acc_id].fill(fruit.weight_lbs)
                self.pack_lbs += fruit.weight_lbs
            elif fruit.grade == FruitGrade.JUICE:
                self.juice_lbs += fruit.weight_lbs
    
    def _pdg_production(self, upstream_available_lbs: float, dt_sec: float) -> None:
        """PDGs produce bags, draw from accumulators"""
        remaining_upstream = upstream_available_lbs

        for pdg in self.pdgs:
            # Snapshot bags before production
            prev_bags = {b.bagger_id: b.bags_completed for b in pdg.baggers}

            consumed, from_upstream = pdg.produce(remaining_upstream, dt_sec)
            remaining_upstream -= from_upstream

            # Track only NEW production this step
            for bagger in pdg.baggers:
                new_bags = bagger.bags_completed - prev_bags[bagger.bagger_id]
                self.total_lbs_produced += new_bags * bagger.bag_size_lbs
    
    # ========================================================================
    # EXTERNAL CONTROL
    # ========================================================================
    
    def load_bin(self, weight_lbs: float) -> None:
        """Load a new bin"""
        self.active_bin = Bin(weight_lbs)
    
    def set_bin_speed(self, speed_pct: float) -> None:
        """Manual bin speed (MANUAL mode)"""
        self.manual_bin_speed_pct = max(0, min(100, speed_pct))
    
    def set_bagger_speed(self, bagger_id: int, speed_pct: float) -> None:
        """Manual bagger speed"""
        for pdg in self.pdgs:
            for bagger in pdg.baggers:
                if bagger.bagger_id == bagger_id:
                    bagger.manual_speed_pct = max(0, min(100, speed_pct))
    
    def toggle_bagger(self, bagger_id: int, active: bool) -> None:
        """Enable/disable bagger"""
        for pdg in self.pdgs:
            for bagger in pdg.baggers:
                if bagger.bagger_id == bagger_id:
                    bagger.active = active
    
    def set_control_mode(self, mode: ControlMode) -> None:
        """Switch control mode"""
        self.control_mode = mode
    
    # ========================================================================
    # METRICS & STATE
    # ========================================================================
    
    def get_state(self) -> Dict:
        """Return complete state snapshot"""
        return {
            "time_sec": self.current_time_sec,
            "control_mode": self.control_mode.value,
            "upstream_speed_multiplier": round(self.upstream_speed_multiplier, 3),
            "active_bin": {
                "remaining_lbs": self.active_bin.remaining_weight_lbs if self.active_bin else 0,
                "total_bins_completed": self.bins_completed
            },
            "accumulators": [
                {
                    "id": a.accumulator_id,
                    "fill_lbs": round(a.current_fill_lbs, 1),
                    "fill_pct": round(a.fill_pct(), 1),
                    "capacity_lbs": a.capacity_lbs
                }
                for a in self.accumulators
            ],
            "baggers": [
                {
                    "id": b.bagger_id,
                    "pdg": b.pdg_id,
                    "bag_size": b.bag_size_lbs,
                    "active": b.active,
                    "speed_pct": round(b.manual_speed_pct, 1),
                    "bags_completed": b.bags_completed,
                    "demand_lbs_sec": round(b.demand_lbs_per_sec(), 3)
                }
                for pdg in self.pdgs
                for b in pdg.baggers
            ],
            "lanes": [
                {
                    "id": l.lane_id,
                    "buffer_fill": len(l.buffer),
                    "utilization_pct": round(l.utilization_pct(), 1)
                }
                for l in self.lanes
            ],
            "streams": {
                "pack_lbs": round(self.pack_lbs, 1),
                "juice_lbs": round(self.juice_lbs, 1),
                "recycle_buffer_lbs": round(self.recycle_buffer_mass_lbs, 1)
            },
            "output": {
                "total_lbs_produced": round(self.total_lbs_produced, 1),
                "cases_completed": self.cases_completed,
                "pallets_completed": self.pallets_completed
            }
        }
    
    def get_metrics(self) -> Dict:
        """Performance metrics"""
        throughput_lbs_per_hour = (self.total_lbs_produced / max(1, self.current_time_sec)) * 3600 if self.current_time_sec > 0 else 0
        
        total_stream_lbs = self.pack_lbs + self.juice_lbs
        recycle_rate_pct = 100.0 * self.recycle_lbs / total_stream_lbs if total_stream_lbs > 0 else 0
        
        bagger_utilization = []
        for pdg in self.pdgs:
            for bagger in pdg.baggers:
                util = (bagger.bags_completed / (30 * self.current_time_sec / 60)) * 100 if self.current_time_sec > 0 else 0
                bagger_utilization.append(util)
        
        avg_bagger_util = sum(bagger_utilization) / len(bagger_utilization) if bagger_utilization else 0
        
        return {
            "throughput_lbs_per_hour": round(throughput_lbs_per_hour, 1),
            "pack_lbs_total": round(self.pack_lbs, 1),
            "juice_lbs_total": round(self.juice_lbs, 1),
            "recycle_rate_pct": round(recycle_rate_pct, 1),
            "avg_bagger_utilization_pct": round(avg_bagger_util, 1),
            "avg_accumulator_fill_pct": round(
                sum(a.fill_pct() for a in self.accumulators) / len(self.accumulators), 1
            )
        }


# ============================================================================
# BIN
# ============================================================================

@dataclass
class Bin:
    """Finite source of fruit"""
    initial_weight_lbs: float
    remaining_weight_lbs: float = field(init=False)
    
    def __post_init__(self):
        self.remaining_weight_lbs = self.initial_weight_lbs


# ============================================================================
# EXAMPLE USAGE
# ============================================================================

if __name__ == "__main__":
    sim = ProductionLineSimulator()
    
    # Load bins and run
    sim.load_bin(750.0)
    sim.set_control_mode(ControlMode.AUTO)
    
    # Run 10 seconds
    for _ in range(100):
        sim.step(0.1)
    
    # Print final state
    print(json.dumps(sim.get_state(), indent=2))
    print("\n" + "="*60)
    print("METRICS")
    print("="*60)
    print(json.dumps(sim.get_metrics(), indent=2))
