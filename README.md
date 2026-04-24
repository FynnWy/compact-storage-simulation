PROJECT CONTEXT: Modular Simulation of an Automated Storage System

We are developing a simulation in Python for an automated compact storage system similar to AutoStore. The system consists of a dense grid of vertical stacks where bins are stored on top of each other without horizontal aisles.

The simulation focuses on modeling and evaluating different retrieval strategies under identical conditions.

-------------------------------------
CORE IDEA
-------------------------------------

The system simulates how bins are retrieved from a dense storage structure using robots. Access to bins can be restricted, requiring other bins to be moved first.

The goal is to analyze system performance depending on different strategies and constraints.

-------------------------------------
SIMULATION APPROACH
-------------------------------------

- The simulation is event-driven (discrete event simulation)
- Time progresses via scheduled events
- The system processes events sequentially in time order

-------------------------------------
KEY CONCEPTS
-------------------------------------

1. State
   Represents the physical system (grid, stacks, bins, robots).
   It only contains data and no decision-making logic.

2. Requests
   Represent retrieval demands for specific bins.
   They arrive over time and may include deadlines.

3. Events
   Represent things happening at specific times (e.g. request arrival, robot actions, completion).
   Events drive the simulation forward.

4. Queues
   - Requests wait in a queue until they are processed
   - Events are scheduled and executed based on time

5. Strategies
   Define how a bin is retrieved from the storage system.
   A strategy determines the sequence of required operations (e.g. removing blocking bins).

6. Execution
   The system translates abstract plans into concrete actions that modify the state.

-------------------------------------
IMPORTANT DESIGN PRINCIPLES
-------------------------------------

- Clear separation of concerns:
  - Planning (what should happen)
  - Execution (how it happens)
  - Scheduling (which task next)
  - State (data only)

- Modularity:
  Different strategies must be interchangeable without changing the rest of the system.

- Simplicity first:
  Start with simple logic and extend later.

- No business logic inside data objects:
  Entities should not contain complex behavior.

-------------------------------------
SIMULATION GOAL
-------------------------------------

The goal is not just to simulate correctness, but to compare different approaches and measure:

- retrieval time
- number of movements
- delays
- resource utilization

-------------------------------------
EXPECTATIONS FOR CODE
-------------------------------------

- Write clean, modular, readable Python code
- Avoid large monolithic classes
- Keep responsibilities clearly separated
- Prefer simple, explicit logic over abstraction
- Make the system easy to extend later