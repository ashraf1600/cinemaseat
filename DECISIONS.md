The three primary decisions are:

### Decision 1 --- Single Django/DRF service vs microservices

**Chosen:** Single Django/DRF backend.

**Reason:** The contest prioritizes correctness, testing,
containerization, and deployment within a short development window. A
modular monolith reduces network failure points and operational
complexity.

**Trade-off:** Independent scaling of individual services is less
flexible.

### Decision 2 --- PostgreSQL as the concurrency authority

**Chosen:** PostgreSQL transactions and row-level locking.

**Reason:** Seat ownership must be decided atomically by the database to
prevent two concurrent requests from successfully claiming the same
seat.

**Trade-off:** High contention can increase database lock waiting and
latency.

### Decision 3 --- Poridhi VM deployment

**Chosen:** Poridhi VM + load balancer.

**Reason:** It is the simpler deployment path for the hackathon and
reduces infrastructure complexity.

**Trade-off:** AWS-specific scalability and infrastructure capabilities
are not used in the primary deployment.
