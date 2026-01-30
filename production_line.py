"""
Citrus Production Line Simulator
Demand-driven, accumulator-controlled mass-flow system
"""

from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Optional
from enum import Enum
import json
import random
import tkinter as tk
from tkinter import ttk


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
    _prev_bags: int = 0  # For rate calculation
    _rate_bags_per_min: float = 0.0

    def update_rate(self, dt_sec: float) -> None:
        """Update measured bags/min from recent production"""
        new_bags = self.bags_completed - self._prev_bags
        if dt_sec > 0:
            self._rate_bags_per_min = (new_bags / dt_sec) * 60.0
        self._prev_bags = self.bags_completed

    @property
    def bags_per_min(self) -> float:
        return self._rate_bags_per_min

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
        self.partial_fruit_count = 0.0  # Fractional fruit accumulator
        self.next_accumulator_id = 0  # Round-robin counter for even distribution
        
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

        # Accumulate fractional fruit across steps
        self.partial_fruit_count += actual_fruit_rate * dt_sec
        num_fruits = int(self.partial_fruit_count)
        self.partial_fruit_count -= num_fruits
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
        """Route classified fruit to accumulators (round-robin) or juice"""
        for fruit in classified_fruits:
            if fruit.grade == FruitGrade.PACK:
                acc_id = self.next_accumulator_id % len(self.accumulators)
                self.next_accumulator_id += 1
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

        # Update bagger rate measurements
        for pdg in self.pdgs:
            for bagger in pdg.baggers:
                bagger.update_rate(dt_sec)

        # Cases and pallets from cumulative output
        self.cases_completed = int(self.total_lbs_produced / self.case_size_lbs)
        self.pallets_completed = self.cases_completed // self.pallet_size_cases
    
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
                    "bags_per_min": round(b.bags_per_min, 1),
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
# TKINTER GUI DASHBOARD & CONTROLLER
# ============================================================================

class SimulatorGUI:
    """Tkinter GUI for live simulation display and interactive control."""

    BG = "#0a0e27"
    CARD_BG = "#1a1f3a"
    INPUT_BG = "#0f1428"
    BORDER = "#2d3561"
    TEXT = "#e8eaed"
    ACCENT = "#4da6ff"
    GREEN = "#2d7a2d"
    YELLOW = "#cc9933"
    RED = "#cc3333"
    MUTED = "#888888"

    def __init__(self) -> None:
        self.sim = ProductionLineSimulator()
        self.sim.set_control_mode(ControlMode.AUTO)
        self.dt = 0.1
        self.running = False
        self.sim_speed = 1

        self.root = tk.Tk()
        self.root.title("Citrus Production Line Simulator")
        self.root.configure(bg=self.BG)
        self.root.geometry("1100x820")

        self._build_ui()
        self._tick()
        self.root.mainloop()

    # ── UI CONSTRUCTION ─────────────────────────────────────────────────

    def _build_ui(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TLabel", background=self.CARD_BG, foreground=self.TEXT,
                         font=("Consolas", 9))
        style.configure("Head.TLabel", foreground=self.ACCENT,
                         font=("Consolas", 10, "bold"))
        style.configure("Big.TLabel", foreground=self.ACCENT,
                         font=("Consolas", 13, "bold"))
        style.configure("TFrame", background=self.CARD_BG)
        style.configure("Dark.TFrame", background=self.BG)
        style.configure("TButton", font=("Consolas", 9))
        style.configure("TScale", background=self.CARD_BG)

        # Title
        title = tk.Label(self.root, text="CITRUS PRODUCTION LINE SIMULATOR",
                          bg=self.BG, fg=self.ACCENT,
                          font=("Consolas", 16, "bold"))
        title.pack(pady=(10, 5))

        # Main paned layout: left=controls, right=display
        main = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, bg=self.BG,
                               sashwidth=4, bd=0)
        main.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        left = tk.Frame(main, bg=self.BG, width=340)
        right = tk.Frame(main, bg=self.BG)
        main.add(left, minsize=300)
        main.add(right, minsize=500)

        self._build_controls(left)
        self._build_display(right)

    def _card(self, parent, title_text: str) -> tk.Frame:
        """Create a styled card frame with title."""
        card = tk.Frame(parent, bg=self.CARD_BG, bd=1,
                         highlightbackground=self.BORDER, highlightthickness=1)
        card.pack(fill=tk.X, padx=5, pady=4)
        lbl = tk.Label(card, text=title_text, bg=self.CARD_BG, fg=self.ACCENT,
                        font=("Consolas", 10, "bold"), anchor="w")
        lbl.pack(fill=tk.X, padx=8, pady=(6, 2))
        body = tk.Frame(card, bg=self.CARD_BG)
        body.pack(fill=tk.X, padx=8, pady=(0, 8))
        return body

    # ── LEFT PANEL: CONTROLS ────────────────────────────────────────────

    def _build_controls(self, parent) -> None:
        # Simulation controls
        body = self._card(parent, "Simulation")
        btn_row = tk.Frame(body, bg=self.CARD_BG)
        btn_row.pack(fill=tk.X, pady=2)

        self.play_btn = tk.Button(btn_row, text="Start", width=8,
                                   bg=self.ACCENT, fg=self.BG,
                                   font=("Consolas", 9, "bold"),
                                   command=self._toggle_run)
        self.play_btn.pack(side=tk.LEFT, padx=(0, 5))

        tk.Button(btn_row, text="Reset", width=8,
                  bg="#4a4a4a", fg=self.TEXT,
                  font=("Consolas", 9),
                  command=self._reset).pack(side=tk.LEFT)

        spd_row = tk.Frame(body, bg=self.CARD_BG)
        spd_row.pack(fill=tk.X, pady=4)
        tk.Label(spd_row, text="Speed:", bg=self.CARD_BG, fg=self.MUTED,
                 font=("Consolas", 9)).pack(side=tk.LEFT)
        self.speed_var = tk.IntVar(value=1)
        self.speed_scale = tk.Scale(spd_row, from_=1, to=50,
                                     orient=tk.HORIZONTAL,
                                     variable=self.speed_var,
                                     bg=self.CARD_BG, fg=self.TEXT,
                                     highlightbackground=self.CARD_BG,
                                     troughcolor=self.INPUT_BG,
                                     font=("Consolas", 8),
                                     showvalue=True, length=180)
        self.speed_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Control mode
        body = self._card(parent, "Control Mode")
        self.mode_var = tk.StringVar(value="auto")
        for val, label in [("auto", "AUTO (Accumulator)"), ("manual", "MANUAL")]:
            tk.Radiobutton(body, text=label, variable=self.mode_var, value=val,
                           bg=self.CARD_BG, fg=self.TEXT,
                           selectcolor=self.INPUT_BG,
                           activebackground=self.CARD_BG,
                           activeforeground=self.TEXT,
                           font=("Consolas", 9),
                           command=self._set_mode).pack(anchor="w")

        # Bin controls
        body = self._card(parent, "Bin Management")
        self.auto_bin_var = tk.BooleanVar(value=True)
        tk.Checkbutton(body, text="Auto Bin Loading",
                        variable=self.auto_bin_var,
                        bg=self.CARD_BG, fg=self.TEXT,
                        selectcolor=self.INPUT_BG,
                        activebackground=self.CARD_BG,
                        font=("Consolas", 9),
                        command=self._toggle_auto_bin).pack(anchor="w")

        bin_row = tk.Frame(body, bg=self.CARD_BG)
        bin_row.pack(fill=tk.X, pady=4)
        tk.Label(bin_row, text="Manual bin (lbs):", bg=self.CARD_BG,
                 fg=self.MUTED, font=("Consolas", 9)).pack(side=tk.LEFT)
        self.bin_weight_entry = tk.Entry(bin_row, width=6, bg=self.INPUT_BG,
                                          fg=self.TEXT, insertbackground=self.TEXT,
                                          font=("Consolas", 9))
        self.bin_weight_entry.insert(0, "750")
        self.bin_weight_entry.pack(side=tk.LEFT, padx=4)
        tk.Button(bin_row, text="Load", bg="#4a4a4a", fg=self.TEXT,
                  font=("Consolas", 9),
                  command=self._load_bin).pack(side=tk.LEFT)

        spd = tk.Frame(body, bg=self.CARD_BG)
        spd.pack(fill=tk.X, pady=2)
        tk.Label(spd, text="Dump Speed:", bg=self.CARD_BG, fg=self.MUTED,
                 font=("Consolas", 9)).pack(side=tk.LEFT)
        self.bin_speed_var = tk.IntVar(value=100)
        self.bin_speed_lbl = tk.Label(spd, text="100%", bg=self.CARD_BG,
                                       fg=self.TEXT, font=("Consolas", 9))
        self.bin_speed_lbl.pack(side=tk.RIGHT)
        tk.Scale(spd, from_=0, to=100, orient=tk.HORIZONTAL,
                 variable=self.bin_speed_var,
                 bg=self.CARD_BG, fg=self.TEXT,
                 highlightbackground=self.CARD_BG,
                 troughcolor=self.INPUT_BG,
                 font=("Consolas", 8),
                 showvalue=False, length=140,
                 command=self._set_bin_speed).pack(side=tk.LEFT,
                                                    fill=tk.X, expand=True)

        # Bagger controls
        body = self._card(parent, "Bagger Controls")
        self.bagger_frames = []
        self.bagger_speed_vars = []
        self.bagger_active_vars = []
        self.bagger_toggle_btns = []
        bag_sizes = [1, 2, 3, 5]

        for i in range(8):
            pdg_id = i // 2
            row = tk.Frame(body, bg=self.INPUT_BG, bd=1,
                            highlightbackground=self.BORDER,
                            highlightthickness=1)
            row.pack(fill=tk.X, pady=1)

            tk.Label(row, text=f"B{i} ({bag_sizes[pdg_id]}lb)",
                     bg=self.INPUT_BG, fg=self.TEXT,
                     font=("Consolas", 8), width=8).pack(side=tk.LEFT, padx=2)

            spd_var = tk.IntVar(value=100)
            self.bagger_speed_vars.append(spd_var)
            tk.Scale(row, from_=0, to=100, orient=tk.HORIZONTAL,
                     variable=spd_var, bg=self.INPUT_BG, fg=self.TEXT,
                     highlightbackground=self.INPUT_BG,
                     troughcolor=self.CARD_BG,
                     font=("Consolas", 7),
                     showvalue=False, length=100,
                     command=lambda v, idx=i: self._set_bagger_speed(idx, v)
                     ).pack(side=tk.LEFT)

            act_var = tk.BooleanVar(value=True)
            self.bagger_active_vars.append(act_var)
            btn = tk.Button(row, text="ON", width=4,
                             bg=self.GREEN, fg=self.TEXT,
                             font=("Consolas", 8, "bold"),
                             command=lambda idx=i: self._toggle_bagger(idx))
            btn.pack(side=tk.RIGHT, padx=2)
            self.bagger_toggle_btns.append(btn)

            self.bagger_frames.append(row)

    # ── RIGHT PANEL: LIVE DISPLAY ───────────────────────────────────────

    def _build_display(self, parent) -> None:
        # Status bar
        self.status_lbl = tk.Label(parent, text="STOPPED", bg=self.BG,
                                    fg=self.YELLOW,
                                    font=("Consolas", 10, "bold"),
                                    anchor="w")
        self.status_lbl.pack(fill=tk.X, padx=5, pady=(0, 4))

        # Scrollable canvas for display sections
        canvas = tk.Canvas(parent, bg=self.BG, highlightthickness=0)
        scrollbar = tk.Scrollbar(parent, orient=tk.VERTICAL,
                                  command=canvas.yview)
        self.display_frame = tk.Frame(canvas, bg=self.BG)

        self.display_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=self.display_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Bind mousewheel
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # Build display sections
        self._build_bin_display()
        self._build_acc_display()
        self._build_bagger_display()
        self._build_production_display()
        self._build_lane_display()
        self._build_path_display()

    def _section(self, title_text: str) -> tk.Frame:
        """Add a display section to the right panel."""
        frm = tk.Frame(self.display_frame, bg=self.CARD_BG, bd=1,
                        highlightbackground=self.BORDER,
                        highlightthickness=1)
        frm.pack(fill=tk.X, padx=5, pady=3)
        tk.Label(frm, text=title_text, bg=self.CARD_BG, fg=self.ACCENT,
                 font=("Consolas", 10, "bold"), anchor="w").pack(
            fill=tk.X, padx=8, pady=(6, 2))
        body = tk.Frame(frm, bg=self.CARD_BG)
        body.pack(fill=tk.X, padx=8, pady=(0, 8))
        return body

    def _build_bin_display(self) -> None:
        body = self._section("BINS")
        self.bin_lbl = tk.Label(body, text="", bg=self.CARD_BG, fg=self.TEXT,
                                 font=("Consolas", 9), anchor="w")
        self.bin_lbl.pack(fill=tk.X)

    def _build_acc_display(self) -> None:
        body = self._section("ACCUMULATORS")
        self.acc_bars = []
        self.acc_lbls = []
        for i in range(4):
            row = tk.Frame(body, bg=self.CARD_BG)
            row.pack(fill=tk.X, pady=1)
            lbl = tk.Label(row, text=f"Acc {i}:", bg=self.CARD_BG,
                            fg=self.TEXT, font=("Consolas", 9), width=6,
                            anchor="w")
            lbl.pack(side=tk.LEFT)
            bar_bg = tk.Frame(row, bg=self.INPUT_BG, height=16, width=200)
            bar_bg.pack(side=tk.LEFT, padx=4)
            bar_bg.pack_propagate(False)
            bar_fill = tk.Frame(bar_bg, bg=self.ACCENT, height=16)
            bar_fill.place(x=0, y=0, relheight=1.0, relwidth=0.0)
            info = tk.Label(row, text="  0.0%   0/3600 lbs", bg=self.CARD_BG,
                             fg=self.MUTED, font=("Consolas", 9), anchor="w")
            info.pack(side=tk.LEFT, padx=4)
            self.acc_bars.append(bar_fill)
            self.acc_lbls.append(info)

    def _build_bagger_display(self) -> None:
        body = self._section("BAGGERS (PDG x 2)")
        self.bagger_lbls = []
        for i in range(8):
            lbl = tk.Label(body, text="", bg=self.CARD_BG, fg=self.TEXT,
                            font=("Consolas", 9), anchor="w")
            lbl.pack(fill=tk.X)
            self.bagger_lbls.append(lbl)

    def _build_production_display(self) -> None:
        body = self._section("PRODUCTION")
        self.prod_lbl = tk.Label(body, text="", bg=self.CARD_BG, fg=self.TEXT,
                                  font=("Consolas", 9), anchor="w",
                                  justify=tk.LEFT)
        self.prod_lbl.pack(fill=tk.X)

    def _build_lane_display(self) -> None:
        body = self._section("SINGULATOR LANES")
        self.lane_lbl = tk.Label(body, text="", bg=self.CARD_BG, fg=self.TEXT,
                                  font=("Consolas", 9), anchor="w")
        self.lane_lbl.pack(fill=tk.X)

    def _build_path_display(self) -> None:
        body = self._section("FRUIT PATH")
        path = (
            "Bin > Metering > Unstack > Grade(-15%juice) > Wash/Dry/Wax\n"
            "  > Singulator(10 lanes) > Camera(-10%recycle,-10%juice)\n"
            "  > Accumulators(4) > PDGs(4) > Baggers(8) > Cases > Pallets"
        )
        tk.Label(body, text=path, bg=self.CARD_BG, fg=self.GREEN,
                 font=("Consolas", 9), anchor="w",
                 justify=tk.LEFT).pack(fill=tk.X)

    # ── CONTROL CALLBACKS ───────────────────────────────────────────────

    def _toggle_run(self) -> None:
        self.running = not self.running
        self.play_btn.config(
            text="Pause" if self.running else "Start",
            bg=self.YELLOW if self.running else self.ACCENT
        )

    def _reset(self) -> None:
        self.running = False
        self.play_btn.config(text="Start", bg=self.ACCENT)
        self.sim = ProductionLineSimulator()
        self.sim.set_control_mode(
            ControlMode.AUTO if self.mode_var.get() == "auto"
            else ControlMode.MANUAL
        )
        self._update_display()

    def _set_mode(self) -> None:
        mode = ControlMode.AUTO if self.mode_var.get() == "auto" \
            else ControlMode.MANUAL
        self.sim.set_control_mode(mode)

    def _toggle_auto_bin(self) -> None:
        self.sim.auto_bin_enabled = self.auto_bin_var.get()

    def _load_bin(self) -> None:
        try:
            w = float(self.bin_weight_entry.get())
        except ValueError:
            w = 750.0
        self.sim.load_bin(w)

    def _set_bin_speed(self, val) -> None:
        v = int(float(val))
        self.sim.set_bin_speed(v)
        self.bin_speed_lbl.config(text=f"{v}%")

    def _set_bagger_speed(self, idx: int, val) -> None:
        v = int(float(val))
        self.sim.set_bagger_speed(idx, v)

    def _toggle_bagger(self, idx: int) -> None:
        cur = self.bagger_active_vars[idx].get()
        new_val = not cur
        self.bagger_active_vars[idx].set(new_val)
        self.sim.toggle_bagger(idx, new_val)
        btn = self.bagger_toggle_btns[idx]
        btn.config(text="ON" if new_val else "OFF",
                   bg=self.GREEN if new_val else "#4a4a4a")

    # ── SIMULATION LOOP ─────────────────────────────────────────────────

    def _tick(self) -> None:
        if self.running:
            self.sim_speed = self.speed_var.get()
            for _ in range(self.sim_speed):
                self.sim.step(self.dt)
        self._update_display()
        self.root.after(50, self._tick)

    def _update_display(self) -> None:
        state = self.sim.get_state()
        metrics = self.sim.get_metrics()

        # Status bar
        if self.running:
            self.status_lbl.config(
                text=f"  RUNNING  |  Speed: {self.speed_var.get()}x  |  "
                     f"Time: {state['time_sec']:.1f}s  |  "
                     f"Mode: {state['control_mode'].upper()}  |  "
                     f"Multiplier: {state['upstream_speed_multiplier']:.2f}",
                fg=self.GREEN)
        else:
            self.status_lbl.config(
                text=f"  STOPPED  |  Time: {state['time_sec']:.1f}s  |  "
                     f"Mode: {state['control_mode'].upper()}",
                fg=self.YELLOW)

        # Bins
        bi = state["active_bin"]
        self.bin_lbl.config(
            text=f"Active Bin: {bi['remaining_lbs']:.0f} lbs remaining    "
                 f"Bins Completed: {bi['total_bins_completed']}"
        )

        # Accumulators
        for i, acc in enumerate(state["accumulators"]):
            pct = acc["fill_pct"]
            frac = max(0.0, min(1.0, pct / 100.0))
            self.acc_bars[i].place(x=0, y=0, relheight=1.0, relwidth=frac)
            if pct > 80:
                self.acc_bars[i].config(bg=self.RED)
            elif pct > 50:
                self.acc_bars[i].config(bg=self.YELLOW)
            else:
                self.acc_bars[i].config(bg=self.ACCENT)
            self.acc_lbls[i].config(
                text=f"  {pct:5.1f}%   {acc['fill_lbs']:.0f}/{acc['capacity_lbs']:.0f} lbs"
            )

        # Baggers
        bag_sizes = [1, 2, 3, 5]
        for i, b in enumerate(state["baggers"]):
            pdg_id = b["pdg"]
            on_str = "ON " if b["active"] else "OFF"
            self.bagger_lbls[i].config(
                text=f"B{b['id']} (PDG{pdg_id}, {b['bag_size']:.0f}lb) "
                     f"[{on_str}] "
                     f"Spd:{b['speed_pct']:3.0f}%  "
                     f"Rate:{b['bags_per_min']:5.1f} bags/min  "
                     f"Bags:{b['bags_completed']:6d}",
                fg=self.GREEN if b["active"] else self.RED
            )

        # Production
        out = state["output"]
        streams = state["streams"]
        self.prod_lbl.config(
            text=f"Total Produced: {out['total_lbs_produced']:.1f} lbs\n"
                 f"Pack Stream:    {streams['pack_lbs']:.1f} lbs     "
                 f"Juice Stream: {streams['juice_lbs']:.1f} lbs\n"
                 f"Cases (30 lbs): {out['cases_completed']}         "
                 f"Pallets (60 cases): {out['pallets_completed']}\n"
                 f"Throughput:     {metrics['throughput_lbs_per_hour']:.0f} lbs/hr   "
                 f"Bagger Util: {metrics['avg_bagger_utilization_pct']:.1f}%"
        )

        # Lanes
        parts = [f"L{l['id']}:{l['utilization_pct']:3.0f}%"
                 for l in state["lanes"]]
        self.lane_lbl.config(text="  ".join(parts))


if __name__ == "__main__":
    SimulatorGUI()
