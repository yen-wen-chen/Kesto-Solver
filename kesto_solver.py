"""Kesto level painter and BFS solver.

Run with:
    python3 kesto_solver.py

If Tk is unavailable, the script starts a browser-based painter/solver instead.

The puzzle is modeled as an 8x8 board. Each move pushes every box one cell in
the same direction. Boxes are processed from the leading edge, so a contiguous
line of boxes can move together if the front box is not blocked.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import queue
import sys
import threading
import time
import webbrowser

try:
    import tkinter as tk
    from tkinter import messagebox
except ModuleNotFoundError as exc:
    tk = None  # type: ignore[assignment]
    messagebox = None  # type: ignore[assignment]
    TKINTER_IMPORT_ERROR = exc
else:
    TKINTER_IMPORT_ERROR = None


GRID_SIZE = 8
CELL_SIZE = 56
MAX_BFS_STATES = 500_000

EMPTY = "empty"
BOX = "box"
TARGET = "target"
WALL = "wall"

COLORS = {
    EMPTY: "#f8fafc",
    BOX: "#f59e0b",
    TARGET: "#2563eb",
    WALL: "#6b7280",
}

DIRECTIONS = {
    "Up": (-1, 0),
    "Down": (1, 0),
    "Left": (0, -1),
    "Right": (0, 1),
}

Position = tuple[int, int]
State = tuple[Position, ...]


@dataclass(frozen=True)
class SolveResult:
    moves: list[str] | None
    visited_states: int
    reached_limit: bool
    elapsed_seconds: float


def normalize(positions: set[Position] | list[Position] | tuple[Position, ...]) -> State:
    return tuple(sorted(positions))


def in_bounds(position: Position) -> bool:
    row, col = position
    return 0 <= row < GRID_SIZE and 0 <= col < GRID_SIZE


def move_state(state: State, walls: set[Position], direction: str) -> State:
    """Move all boxes one cell in the requested direction."""
    row_delta, col_delta = DIRECTIONS[direction]

    if row_delta == -1:
        ordered_boxes = sorted(state, key=lambda pos: pos[0])
    elif row_delta == 1:
        ordered_boxes = sorted(state, key=lambda pos: pos[0], reverse=True)
    elif col_delta == -1:
        ordered_boxes = sorted(state, key=lambda pos: pos[1])
    else:
        ordered_boxes = sorted(state, key=lambda pos: pos[1], reverse=True)

    new_positions: set[Position] = set()
    for row, col in ordered_boxes:
        destination = (row + row_delta, col + col_delta)
        if (
            not in_bounds(destination)
            or destination in walls
            or destination in new_positions
        ):
            new_positions.add((row, col))
        else:
            new_positions.add(destination)

    return normalize(new_positions)


def reconstruct_path(
    parents: dict[State, tuple[State | None, str | None]], end_state: State
) -> list[str]:
    moves: list[str] = []
    state = end_state
    while True:
        parent, move = parents[state]
        if parent is None:
            break
        if move is not None:
            moves.append(move)
        state = parent
    moves.reverse()
    return moves


def solve_bfs(
    boxes: set[Position],
    targets: set[Position],
    walls: set[Position],
    max_states: int = MAX_BFS_STATES,
) -> SolveResult:
    start_time = time.perf_counter()
    start_state = normalize(boxes)
    target_state = normalize(targets)

    queue_to_visit: deque[State] = deque([start_state])
    parents: dict[State, tuple[State | None, str | None]] = {
        start_state: (None, None)
    }

    while queue_to_visit and len(parents) <= max_states:
        state = queue_to_visit.popleft()
        if state == target_state:
            return SolveResult(
                moves=reconstruct_path(parents, state),
                visited_states=len(parents),
                reached_limit=False,
                elapsed_seconds=time.perf_counter() - start_time,
            )

        for direction in DIRECTIONS:
            next_state = move_state(state, walls, direction)
            if next_state == state or next_state in parents:
                continue
            parents[next_state] = (state, direction)
            queue_to_visit.append(next_state)

    return SolveResult(
        moves=None,
        visited_states=len(parents),
        reached_limit=bool(queue_to_visit),
        elapsed_seconds=time.perf_counter() - start_time,
    )


def states_from_moves(boxes: set[Position], walls: set[Position], moves: list[str]) -> list[State]:
    states = [normalize(boxes)]
    state = states[0]
    for move in moves:
        state = move_state(state, walls, move)
        states.append(state)
    return states


class KestoSolverApp(tk.Tk if tk is not None else object):
    def __init__(self) -> None:
        if tk is None:
            raise RuntimeError(
                "Tkinter is not available in this Python installation. "
                "Use a Python build that includes Tcl/Tk to run the GUI."
            ) from TKINTER_IMPORT_ERROR

        super().__init__()
        self.title("Kesto Solver")
        self.resizable(False, False)

        self.cells: list[list[str]] = [
            [EMPTY for _ in range(GRID_SIZE)] for _ in range(GRID_SIZE)
        ]
        self.current_tool = tk.StringVar(value=BOX)
        self.status_text = tk.StringVar(value="Paint a level, then click Solve.")
        self.solution_text = tk.StringVar(value="")
        self.display_boxes: State | None = None
        self.solution_states: list[State] = []
        self.solution_index = 0
        self.board_generation = 0
        self.result_queue: queue.Queue[tuple[int, SolveResult | Exception]] = queue.Queue()
        self.solving = False

        self._build_ui()
        self._draw_grid()

    def _build_ui(self) -> None:
        outer = tk.Frame(self, padx=14, pady=14, bg="#e5e7eb")
        outer.grid(row=0, column=0, sticky="nsew")

        self.canvas = tk.Canvas(
            outer,
            width=GRID_SIZE * CELL_SIZE,
            height=GRID_SIZE * CELL_SIZE,
            bg=COLORS[EMPTY],
            highlightthickness=1,
            highlightbackground="#94a3b8",
        )
        self.canvas.grid(row=0, column=0, rowspan=4)
        self.canvas.bind("<Button-1>", self._paint_from_event)
        self.canvas.bind("<B1-Motion>", self._paint_from_event)
        self.canvas.bind("<Button-3>", self._clear_from_event)
        self.canvas.bind("<B3-Motion>", self._clear_from_event)

        controls = tk.Frame(outer, padx=16, bg="#e5e7eb")
        controls.grid(row=0, column=1, sticky="new")

        tk.Label(
            controls,
            text="Paint",
            font=("TkDefaultFont", 13, "bold"),
            bg="#e5e7eb",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        tools = [
            ("Orange boxes", BOX),
            ("Blue targets", TARGET),
            ("Grey walls", WALL),
            ("Eraser", EMPTY),
        ]
        for row_index, (label, value) in enumerate(tools, start=1):
            tk.Radiobutton(
                controls,
                text=label,
                value=value,
                variable=self.current_tool,
                indicatoron=False,
                width=16,
                anchor="w",
                padx=10,
                pady=6,
                bg="#f8fafc",
                selectcolor="#dbeafe",
                command=self._draw_grid,
            ).grid(row=row_index, column=0, sticky="ew", pady=2)

        tk.Button(
            controls,
            text="Solve",
            command=self._solve_current_board,
            width=16,
            pady=6,
        ).grid(row=5, column=0, sticky="ew", pady=(14, 2))

        tk.Button(
            controls,
            text="Clear",
            command=self._clear_board,
            width=16,
            pady=6,
        ).grid(row=6, column=0, sticky="ew", pady=2)

        navigation = tk.Frame(controls, bg="#e5e7eb")
        navigation.grid(row=7, column=0, sticky="ew", pady=(14, 2))
        self.prev_button = tk.Button(
            navigation,
            text="Prev",
            command=self._previous_solution_state,
            width=7,
            state=tk.DISABLED,
        )
        self.prev_button.grid(row=0, column=0, padx=(0, 4))
        self.next_button = tk.Button(
            navigation,
            text="Next",
            command=self._next_solution_state,
            width=7,
            state=tk.DISABLED,
        )
        self.next_button.grid(row=0, column=1, padx=(4, 0))

        tk.Label(
            controls,
            textvariable=self.status_text,
            justify="left",
            anchor="w",
            wraplength=170,
            bg="#e5e7eb",
        ).grid(row=8, column=0, sticky="ew", pady=(14, 8))

        tk.Label(
            controls,
            text="Solution sequence",
            font=("TkDefaultFont", 11, "bold"),
            anchor="w",
            bg="#e5e7eb",
        ).grid(row=9, column=0, sticky="ew", pady=(0, 4))

        self.solution_box = tk.Text(
            controls,
            width=22,
            height=13,
            wrap="word",
            state=tk.DISABLED,
            bg="#f8fafc",
            relief=tk.SOLID,
            borderwidth=1,
        )
        self.solution_box.grid(row=10, column=0, sticky="ew")

    def _draw_grid(self) -> None:
        self.canvas.delete("all")
        boxes_to_draw = self.display_boxes
        if boxes_to_draw is None:
            boxes_to_draw = normalize(self._positions_for(BOX))
        box_set = set(boxes_to_draw)
        target_set = self._positions_for(TARGET)

        for row in range(GRID_SIZE):
            for col in range(GRID_SIZE):
                x0 = col * CELL_SIZE
                y0 = row * CELL_SIZE
                x1 = x0 + CELL_SIZE
                y1 = y0 + CELL_SIZE
                position = (row, col)
                cell = self.cells[row][col]

                if cell == WALL:
                    color = COLORS[WALL]
                elif position in target_set:
                    color = COLORS[TARGET]
                else:
                    color = COLORS[EMPTY]

                if position in box_set:
                    color = "#22c55e" if position in target_set else COLORS[BOX]

                self.canvas.create_rectangle(
                    x0,
                    y0,
                    x1,
                    y1,
                    fill=color,
                    outline="#cbd5e1",
                    width=1,
                )

                if position in target_set and position in box_set:
                    self.canvas.create_oval(
                        x0 + 18,
                        y0 + 18,
                        x1 - 18,
                        y1 - 18,
                        fill=COLORS[TARGET],
                        outline="",
                    )

                if position in box_set:
                    self.canvas.create_text(
                        x0 + CELL_SIZE / 2,
                        y0 + CELL_SIZE / 2,
                        text="B",
                        fill="#111827",
                        font=("TkDefaultFont", 16, "bold"),
                    )
                elif position in target_set:
                    self.canvas.create_text(
                        x0 + CELL_SIZE / 2,
                        y0 + CELL_SIZE / 2,
                        text="T",
                        fill="#ffffff",
                        font=("TkDefaultFont", 16, "bold"),
                    )

        selected_tool = self.current_tool.get()
        self.canvas.create_rectangle(
            2,
            2,
            GRID_SIZE * CELL_SIZE - 2,
            GRID_SIZE * CELL_SIZE - 2,
            outline="#111827" if selected_tool != EMPTY else "#64748b",
            width=2,
        )

    def _paint_from_event(self, event: tk.Event) -> None:
        self._set_cell_from_event(event, self.current_tool.get())

    def _clear_from_event(self, event: tk.Event) -> None:
        self._set_cell_from_event(event, EMPTY)

    def _set_cell_from_event(self, event: tk.Event, value: str) -> None:
        row = event.y // CELL_SIZE
        col = event.x // CELL_SIZE
        if not (0 <= row < GRID_SIZE and 0 <= col < GRID_SIZE):
            return

        if self.cells[row][col] == value:
            return

        self.cells[row][col] = value
        self.board_generation += 1
        self._reset_solution_display()
        self._draw_grid()

    def _positions_for(self, cell_type: str) -> set[Position]:
        return {
            (row, col)
            for row in range(GRID_SIZE)
            for col in range(GRID_SIZE)
            if self.cells[row][col] == cell_type
        }

    def _validate_board(
        self,
    ) -> tuple[set[Position], set[Position], set[Position]] | None:
        boxes = self._positions_for(BOX)
        targets = self._positions_for(TARGET)
        walls = self._positions_for(WALL)

        if not boxes:
            messagebox.showerror("Invalid level", "Paint at least one box.")
            return None
        if not targets:
            messagebox.showerror("Invalid level", "Paint at least one target.")
            return None
        if len(boxes) != len(targets):
            messagebox.showerror(
                "Invalid level",
                "The number of boxes must match the number of targets.",
            )
            return None
        if boxes & walls or targets & walls:
            messagebox.showerror(
                "Invalid level",
                "Boxes and targets cannot be painted on walls.",
            )
            return None
        return boxes, targets, walls

    def _solve_current_board(self) -> None:
        if self.solving:
            return

        validated = self._validate_board()
        if validated is None:
            return

        boxes, targets, walls = validated
        generation = self.board_generation
        self.solving = True
        self.status_text.set("Solving...")
        self._set_solution_text("")
        self._set_navigation_enabled(False)

        worker = threading.Thread(
            target=self._solve_worker,
            args=(generation, boxes, targets, walls),
            daemon=True,
        )
        worker.start()
        self.after(80, self._poll_solver)

    def _solve_worker(
        self,
        generation: int,
        boxes: set[Position],
        targets: set[Position],
        walls: set[Position],
    ) -> None:
        try:
            result = solve_bfs(boxes, targets, walls)
            self.result_queue.put((generation, result))
        except Exception as exc:
            self.result_queue.put((generation, exc))

    def _poll_solver(self) -> None:
        try:
            generation, result = self.result_queue.get_nowait()
        except queue.Empty:
            self.after(80, self._poll_solver)
            return

        self.solving = False

        if generation != self.board_generation:
            self.status_text.set("Board changed. Solve again for the new level.")
            return

        if isinstance(result, Exception):
            messagebox.showerror("Solver error", str(result))
            self.status_text.set("Solver failed.")
            return

        self._handle_solution(result)

    def _handle_solution(self, result: SolveResult) -> None:
        if result.moves is None:
            if result.reached_limit:
                self.status_text.set(
                    "No solution found before the search limit "
                    f"({result.visited_states:,} states)."
                )
            else:
                self.status_text.set(
                    f"No solution found after {result.visited_states:,} states."
                )
            self._set_solution_text("")
            self._reset_solution_display()
            self._draw_grid()
            return

        self.solution_states = self._states_from_moves(result.moves)
        self.solution_index = 0
        self.display_boxes = self.solution_states[0] if self.solution_states else None
        self._set_navigation_enabled(len(self.solution_states) > 1)
        self._draw_grid()

        if not result.moves:
            self.status_text.set(
                f"Already solved. Checked {result.visited_states:,} state."
            )
            self._set_solution_text("No moves needed.")
            return

        self.status_text.set(
            f"Solved in {len(result.moves)} moves. "
            f"Visited {result.visited_states:,} states in "
            f"{result.elapsed_seconds:.2f}s. Sequence shown below."
        )
        lines = ["Solution sequence:"]
        lines.extend(f"{index + 1}. {move}" for index, move in enumerate(result.moves))
        self._set_solution_text("\n".join(lines))

    def _states_from_moves(self, moves: list[str]) -> list[State]:
        boxes = self._positions_for(BOX)
        walls = self._positions_for(WALL)
        return states_from_moves(boxes, walls, moves)

    def _set_solution_text(self, text: str) -> None:
        self.solution_box.configure(state=tk.NORMAL)
        self.solution_box.delete("1.0", tk.END)
        self.solution_box.insert("1.0", text)
        self.solution_box.configure(state=tk.DISABLED)

    def _previous_solution_state(self) -> None:
        if not self.solution_states:
            return
        self.solution_index = max(0, self.solution_index - 1)
        self.display_boxes = self.solution_states[self.solution_index]
        self._draw_grid()
        self._update_step_status()

    def _next_solution_state(self) -> None:
        if not self.solution_states:
            return
        self.solution_index = min(len(self.solution_states) - 1, self.solution_index + 1)
        self.display_boxes = self.solution_states[self.solution_index]
        self._draw_grid()
        self._update_step_status()

    def _update_step_status(self) -> None:
        if len(self.solution_states) <= 1:
            return
        self.status_text.set(
            f"Showing step {self.solution_index} of {len(self.solution_states) - 1}."
        )

    def _set_navigation_enabled(self, enabled: bool) -> None:
        state = tk.NORMAL if enabled else tk.DISABLED
        self.prev_button.configure(state=state)
        self.next_button.configure(state=state)

    def _reset_solution_display(self) -> None:
        self.display_boxes = None
        self.solution_states = []
        self.solution_index = 0
        self._set_navigation_enabled(False)

    def _clear_board(self) -> None:
        self.cells = [[EMPTY for _ in range(GRID_SIZE)] for _ in range(GRID_SIZE)]
        self.board_generation += 1
        self.status_text.set("Paint a level, then click Solve.")
        self._set_solution_text("")
        self._reset_solution_display()
        self._draw_grid()


WEB_APP_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Kesto Solver</title>
  <style>
    :root {
      color-scheme: light;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: #111827;
      background: #e5e7eb;
    }
    body {
      margin: 0;
      background: #e5e7eb;
    }
    .app {
      box-sizing: border-box;
      display: flex;
      gap: 18px;
      max-width: 880px;
      margin: 0 auto;
      padding: 18px;
      align-items: flex-start;
    }
    .board {
      display: grid;
      grid-template-columns: repeat(8, 56px);
      grid-template-rows: repeat(8, 56px);
      border: 1px solid #94a3b8;
      background: #cbd5e1;
      user-select: none;
      touch-action: none;
    }
    .cell {
      width: 56px;
      height: 56px;
      border: 1px solid #cbd5e1;
      box-sizing: border-box;
      font: 700 16px/1 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      cursor: pointer;
    }
    .empty { background: #f8fafc; color: #111827; }
    .box { background: #f59e0b; color: #111827; }
    .target { background: #2563eb; color: #ffffff; }
    .wall { background: #6b7280; color: #ffffff; }
    .boxOnTarget { background: #22c55e; color: #111827; }
    .panel {
      width: 250px;
    }
    h1 {
      font-size: 20px;
      line-height: 1.2;
      margin: 0 0 12px;
    }
    h2 {
      font-size: 14px;
      line-height: 1.2;
      margin: 16px 0 8px;
    }
    .tools,
    .actions,
    .steps {
      display: grid;
      gap: 8px;
    }
    .tools {
      grid-template-columns: 1fr 1fr;
    }
    .actions,
    .steps {
      grid-template-columns: 1fr 1fr;
      margin-top: 12px;
    }
    button {
      border: 1px solid #94a3b8;
      background: #f8fafc;
      color: #111827;
      border-radius: 6px;
      min-height: 36px;
      font: 500 14px/1 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    button:hover:not(:disabled) {
      background: #e0f2fe;
    }
    button:disabled {
      color: #9ca3af;
      cursor: default;
    }
    .tool.active {
      background: #dbeafe;
      border-color: #2563eb;
    }
    .status {
      min-height: 44px;
      margin-top: 14px;
      font-size: 14px;
      line-height: 1.35;
    }
    .sequence {
      width: 100%;
      height: 190px;
      box-sizing: border-box;
      padding: 10px;
      border: 1px solid #94a3b8;
      border-radius: 6px;
      background: #f8fafc;
      overflow: auto;
      white-space: pre-wrap;
      font: 13px/1.4 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }
    .stepText {
      margin-top: 8px;
      font-size: 13px;
      color: #374151;
    }
    @media (max-width: 760px) {
      .app {
        flex-direction: column;
      }
      .panel {
        width: min(448px, 100%);
      }
    }
  </style>
</head>
<body>
  <main class="app">
    <section>
      <div id="board" class="board" aria-label="Kesto board"></div>
      <div id="stepText" class="stepText"></div>
    </section>
    <aside class="panel">
      <h1>Kesto Solver</h1>
      <h2>Paint</h2>
      <div class="tools">
        <button class="tool active" data-tool="box">Orange boxes</button>
        <button class="tool" data-tool="target">Blue targets</button>
        <button class="tool" data-tool="wall">Grey walls</button>
        <button class="tool" data-tool="empty">Eraser</button>
      </div>
      <div class="actions">
        <button id="solveButton">Solve</button>
        <button id="clearButton">Clear</button>
      </div>
      <div class="steps">
        <button id="prevButton" disabled>Prev</button>
        <button id="nextButton" disabled>Next</button>
      </div>
      <div id="status" class="status">Paint a level, then click Solve.</div>
      <h2>Solution sequence</h2>
      <pre id="sequence" class="sequence"></pre>
    </aside>
  </main>
  <script>
    const GRID_SIZE = 8;
    const board = document.getElementById("board");
    const statusBox = document.getElementById("status");
    const sequenceBox = document.getElementById("sequence");
    const stepText = document.getElementById("stepText");
    const solveButton = document.getElementById("solveButton");
    const clearButton = document.getElementById("clearButton");
    const prevButton = document.getElementById("prevButton");
    const nextButton = document.getElementById("nextButton");

    let cells = Array.from({ length: GRID_SIZE }, () =>
      Array.from({ length: GRID_SIZE }, () => "empty")
    );
    let currentTool = "box";
    let isPainting = false;
    let solutionStates = [];
    let solutionStep = 0;
    let displayBoxes = null;

    function key(row, col) {
      return `${row},${col}`;
    }

    function resetSolution() {
      solutionStates = [];
      solutionStep = 0;
      displayBoxes = null;
      sequenceBox.textContent = "";
      statusBox.textContent = "Paint a level, then click Solve.";
    }

    function render() {
      board.textContent = "";
      const boxKeys = new Set();
      if (displayBoxes) {
        displayBoxes.forEach(([row, col]) => boxKeys.add(key(row, col)));
      }

      for (let row = 0; row < GRID_SIZE; row += 1) {
        for (let col = 0; col < GRID_SIZE; col += 1) {
          const base = cells[row][col];
          const isWall = base === "wall";
          const isTarget = base === "target";
          const isBox = displayBoxes ? boxKeys.has(key(row, col)) : base === "box";
          const cell = document.createElement("button");
          cell.type = "button";
          cell.className = "cell ";
          if (isWall) {
            cell.className += "wall";
          } else if (isBox && isTarget) {
            cell.className += "boxOnTarget";
          } else if (isBox) {
            cell.className += "box";
          } else if (isTarget) {
            cell.className += "target";
          } else {
            cell.className += "empty";
          }
          cell.textContent = isBox ? "B" : (isTarget ? "T" : "");
          cell.addEventListener("pointerdown", (event) => {
            event.preventDefault();
            isPainting = true;
            paint(row, col, event.button === 2 ? "empty" : currentTool);
          });
          cell.addEventListener("pointerenter", (event) => {
            if (isPainting && event.buttons === 1) {
              paint(row, col, currentTool);
            }
          });
          cell.addEventListener("contextmenu", (event) => event.preventDefault());
          board.appendChild(cell);
        }
      }

      const canStep = solutionStates.length > 1;
      prevButton.disabled = !canStep || solutionStep === 0;
      nextButton.disabled = !canStep || solutionStep >= solutionStates.length - 1;
      stepText.textContent = canStep
        ? `Showing step ${solutionStep} of ${solutionStates.length - 1}.`
        : "";
    }

    function paint(row, col, value) {
      if (cells[row][col] === value) {
        return;
      }
      cells[row][col] = value;
      resetSolution();
      render();
    }

    document.addEventListener("pointerup", () => {
      isPainting = false;
    });

    document.querySelectorAll(".tool").forEach((button) => {
      button.addEventListener("click", () => {
        currentTool = button.dataset.tool;
        document.querySelectorAll(".tool").forEach((toolButton) => {
          toolButton.classList.toggle("active", toolButton === button);
        });
      });
    });

    clearButton.addEventListener("click", () => {
      cells = Array.from({ length: GRID_SIZE }, () =>
        Array.from({ length: GRID_SIZE }, () => "empty")
      );
      resetSolution();
      render();
    });

    solveButton.addEventListener("click", async () => {
      statusBox.textContent = "Solving...";
      sequenceBox.textContent = "";
      solveButton.disabled = true;
      try {
        const response = await fetch("/solve", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ cells }),
        });
        const data = await response.json();

        if (!data.ok) {
          resetSolution();
          statusBox.textContent = data.error || "Invalid level.";
          render();
          return;
        }

        if (!data.solvable) {
          resetSolution();
          statusBox.textContent = data.message;
          render();
          return;
        }

        solutionStates = data.states;
        solutionStep = 0;
        displayBoxes = solutionStates[0] || null;
        if (data.moves.length === 0) {
          statusBox.textContent = `Already solved. Checked ${data.visited_states} state.`;
          sequenceBox.textContent = "No moves needed.";
        } else {
          statusBox.textContent =
            `Solved in ${data.moves.length} moves. Sequence shown below.`;
          sequenceBox.textContent =
            "Solution sequence:\\n" +
            data.moves.map((move, index) => `${index + 1}. ${move}`).join("\\n");
        }
        render();
      } catch (error) {
        statusBox.textContent = `Solver request failed: ${error}`;
      } finally {
        solveButton.disabled = false;
      }
    });

    prevButton.addEventListener("click", () => {
      if (solutionStep > 0) {
        solutionStep -= 1;
        displayBoxes = solutionStates[solutionStep];
        render();
      }
    });

    nextButton.addEventListener("click", () => {
      if (solutionStep < solutionStates.length - 1) {
        solutionStep += 1;
        displayBoxes = solutionStates[solutionStep];
        render();
      }
    });

    render();
  </script>
</body>
</html>
"""


def extract_level_from_cells(
    cells: object,
) -> tuple[set[Position], set[Position], set[Position]]:
    if not isinstance(cells, list) or len(cells) != GRID_SIZE:
        raise ValueError("The board must be an 8x8 grid.")

    boxes: set[Position] = set()
    targets: set[Position] = set()
    walls: set[Position] = set()
    valid_cells = {EMPTY, BOX, TARGET, WALL}

    for row_index, row in enumerate(cells):
        if not isinstance(row, list) or len(row) != GRID_SIZE:
            raise ValueError("The board must be an 8x8 grid.")
        for col_index, value in enumerate(row):
            if value not in valid_cells:
                raise ValueError("The board contains an unknown cell type.")
            position = (row_index, col_index)
            if value == BOX:
                boxes.add(position)
            elif value == TARGET:
                targets.add(position)
            elif value == WALL:
                walls.add(position)

    if not boxes:
        raise ValueError("Paint at least one box.")
    if not targets:
        raise ValueError("Paint at least one target.")
    if len(boxes) != len(targets):
        raise ValueError("The number of boxes must match the number of targets.")

    return boxes, targets, walls


def states_for_json(states: list[State]) -> list[list[list[int]]]:
    return [[[row, col] for row, col in state] for state in states]


class KestoWebHandler(BaseHTTPRequestHandler):
    server_version = "KestoSolver/1.0"

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path in {"/", "/index.html"}:
            body = WEB_APP_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        self.send_error(404)

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path != "/solve":
            self.send_error(404)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 100_000:
                raise ValueError("Request is too large.")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            boxes, targets, walls = extract_level_from_cells(payload.get("cells"))
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError, AttributeError) as exc:
            self._send_json({"ok": False, "error": str(exc)})
            return

        result = solve_bfs(boxes, targets, walls)
        if result.moves is None:
            if result.reached_limit:
                message = (
                    "No solution found before the search limit "
                    f"({result.visited_states:,} states)."
                )
            else:
                message = f"No solution found after {result.visited_states:,} states."
            self._send_json(
                {
                    "ok": True,
                    "solvable": False,
                    "message": message,
                    "visited_states": result.visited_states,
                    "elapsed_seconds": result.elapsed_seconds,
                }
            )
            return

        self._send_json(
            {
                "ok": True,
                "solvable": True,
                "moves": result.moves,
                "states": states_for_json(states_from_moves(boxes, walls, result.moves)),
                "visited_states": result.visited_states,
                "elapsed_seconds": result.elapsed_seconds,
            }
        )

    def _send_json(self, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_web_app() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), KestoWebHandler)
    host, port = server.server_address
    url = f"http://{host}:{port}/"
    print(f"Kesto Solver browser UI running at {url}")
    print("Press Ctrl+C to stop the server.")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    if "--tk" in sys.argv:
        if tk is None:
            raise SystemExit(
                "Tkinter is not available in this Python installation. "
                "Run python3 kesto_solver.py for the browser UI instead."
            )
        app = KestoSolverApp()
        app.mainloop()
    else:
        run_web_app()
