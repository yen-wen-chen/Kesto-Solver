# Kesto Solver

Kesto Solver is a small Python app for building and solving Kesto-style
8-by-8 box puzzles.

In Kesto, every move pushes all boxes one cell in the same direction. Boxes
cannot move through walls, board edges, or blocked box chains. The solver uses
breadth-first search to find the shortest sequence of moves that places every
box on a target.

## Features

- Paint an 8-by-8 level directly in the UI.
- Use orange cells for boxes, blue cells for targets, and grey cells for walls.
- Validate that the puzzle has matching box and target counts.
- Solve with breadth-first search.
- Show the full move sequence after solving.
- Step through the solved board state with Prev and Next.
- Run with only the Python standard library.

## Requirements

- Python 3.9 or newer.
- No third-party packages.

The app defaults to a browser-based UI, so it works even when your Python build
does not include Tkinter.

## Run

```bash
python3 kesto_solver.py
```

The script starts a local web server and opens the app in your browser. If the
browser does not open automatically, copy the printed local URL into a browser.

Example terminal output:

```text
Kesto Solver browser UI running at http://127.0.0.1:52341/
Press Ctrl+C to stop the server.
```

## How To Use

1. Select a paint tool.
2. Click or drag on the board to draw boxes, targets, or walls.
3. Right-click or use the eraser to clear cells.
4. Click **Solve**.
5. Read the move list in **Solution sequence**.
6. Use **Prev** and **Next** to step through the solution.

## Optional Tkinter UI

The file also includes a Tkinter UI. Use it only if your Python installation
has Tcl/Tk support:

```bash
python3 kesto_solver.py --tk
```

If Tkinter is unavailable, run the default browser UI instead.

## Solver Notes

- Board size is fixed at 8-by-8.
- Every move is one of `Up`, `Down`, `Left`, or `Right`.
- All boxes attempt to move simultaneously.
- A contiguous line of boxes can move together if the front box is not blocked.
- The search limit is `500,000` visited states.
