# CinemaSeat --- Scalable Cinema Ticket Booking System

A scalable and reliable cinema ticket booking platform built for **Zero
to Production --- Phase 2: The Ultimate Hackathon**.

The system is designed around the central challenge of the contest:
handling sudden high-concurrency demand for popular seats while ensuring
that **the same seat is never sold twice**.

## Team

**Team:** Team_Cha_Coffee

**Repository:** cinemaseat

**Hackathon:** Zero to Production --- Phase 2: The Ultimate Hackathon

**Date:** 8 August 2026

------------------------------------------------------------------------

## Table of contents

-   [Problem understanding](#problem-understanding)
-   [Project goals](#project-goals)
-   [Core features](#core-features)
-   [Architecture](#architecture)
-   [Concurrency and seat-booking
    strategy](#concurrency-and-seat-booking-strategy)
-   [Payment and OTP gateway](#payment-and-otp-gateway)
-   [Booking lifecycle](#booking-lifecycle)
-   [Hold expiration](#hold-expiration)
-   [Tech stack](#tech-stack)
-   [Data model](#data-model)
-   [API](#api)
-   [Frontend experience](#frontend-experience)
-   [Testing and proof](#testing-and-proof)
-   [Deployment](#deployment)
-   [CI/CD](#cicd)
-   [Repository structure](#repository-structure)
-   [Environment variables](#environment-variables)
-   [Local development](#local-development)
-   [Docker setup](#docker-setup)
-   [Judge verification](#judge-verification)
-   [Engineering decisions](#engineering-decisions)
-   [Known limitations](#known-limitations)
-   [Team contributions](#team-contributions)
-   [Attribution](#attribution)

------------------------------------------------------------------------

## Problem understanding

Blockbuster movie releases can create extreme traffic spikes when
thousands of users try to book the same showtime and compete for the
same popular seats.

The challenge is not simply to build a movie ticket website. The system
must remain usable under pressure, handle unreliable payment/OTP
behavior, automatically release abandoned holds, and most importantly:

> **Never sell the same seat twice.**

The contest requires a cinema ticketing platform that can:

-   Browse movies, showtimes, and theatres.
-   Display a live seat map.
-   Hold a seat.
-   Complete payment and confirm a booking.
-   Automatically release a hold when payment is not completed in time.
-   Handle heavy concurrent demand without double-booking.
-   Integrate with the provided payment and OTP gateway.
-   Be containerized, tested, deployable, and reproducible from a clean
    clone.

No cinema admin portal is required. Movies, theatres, showtimes, seat
layouts, and prices are pre-populated.

------------------------------------------------------------------------

## Project goals

The project focuses on five engineering priorities:

1.  **Correctness under concurrency** --- exactly one user should win
    when many users request the same seat simultaneously.
2.  **Reliable asynchronous payment handling** --- payment completion is
    driven by gateway callbacks rather than blocking the booking
    request.
3.  **Idempotency** --- duplicate payment callbacks must not create
    duplicate bookings or payments.
4.  **Automatic hold expiration** --- unpaid seats return to the
    available pool after a configurable TTL.
5.  **Production-ready delivery** --- Docker, CI/CD, deployment,
    documentation, and reproducible setup.

------------------------------------------------------------------------

## Core features

### Customer features

-   Browse movies.
-   Browse theatres and showtimes.
-   View the seat map for a showtime.
-   Select and hold a seat.
-   See the hold expiration countdown.
-   Initiate payment.
-   Receive booking confirmation after successful payment.
-   See booking/payment status.

### Reliability features

-   Database-backed seat state.
-   Concurrency-safe seat holding.
-   Row-level locking for conflicting seat requests.
-   Configurable `HOLD_TTL_SECONDS`.
-   Automatic release of expired holds.
-   Asynchronous payment processing.
-   Idempotent payment callbacks.
-   Safe handling of duplicate callbacks.
-   Safe handling of payment failures and gateway timeouts.
-   Health endpoint independent of gateway availability.

### Engineering features

-   React frontend.
-   Django REST Framework backend.
-   PostgreSQL database.
-   Provided mock payment/OTP gateway.
-   Docker Compose.
-   Automated tests.
-   GitHub Actions CI/CD.
-   Deployed application.
-   Architecture and engineering-decision documentation.

------------------------------------------------------------------------

## Architecture

The project uses a **single Django/DRF backend** rather than multiple
microservices. This keeps the architecture simple enough to build and
operate during the hackathon while still allowing the core booking,
payment, and concurrency logic to be isolated into modules.

!![CinemaSeat Architecture](mermaid-diagram.svg)


### High-level request flow

``` text
React frontend
      |
      | REST API
      v
Django REST Framework
      |
      +--------------------+
      |                    |
      v                    v
 PostgreSQL          Mock Gateway
      |              Payment / OTP
      |
      v
Seat / Hold / Booking state
```

The database is the source of truth for seat availability and booking
state.

------------------------------------------------------------------------

## Concurrency and seat-booking strategy

Concurrency correctness is the most important part of the system.

The critical scenario is:

``` text
100 users
   |
   |  same showtime
   |  same seat
   v
POST /holds/
```

Expected result:

``` text
Requests sent       = 100
Successful holds    = 1
Rejected requests   = 99
Oversell count      = 0
```

### Why row locking is used

Two users may send a hold request at almost exactly the same time.
Application-level checks alone can produce a race condition:

``` text
User A checks seat → AVAILABLE
User B checks seat → AVAILABLE
User A updates     → HELD
User B updates     → HELD
```

To prevent this, the backend performs the critical seat state transition
inside a database transaction and locks the requested `ShowSeat` row
while checking and updating it.

Conceptually:

``` text
BEGIN TRANSACTION
       |
       v
Lock requested ShowSeat row
       |
       v
Check current status
       |
   +---+---+
   |       |
AVAILABLE  HELD/BOOKED
   |       |
   v       v
Create    Reject
hold
   |
   v
COMMIT
```

The database therefore becomes the final authority over who wins the
seat.

------------------------------------------------------------------------

## Payment and OTP gateway

The contest provides a shared mock gateway. The project integrates the
provided gateway instead of creating a custom payment mock.

The gateway exposes:

``` text
POST /charge
POST /refund
POST /otp/send
POST /otp/verify
GET  /health
```

The `/charge` request accepts:

``` text
amount
currency
booking_ref
callback_url
```

The gateway initially returns a pending payment and later calls the
supplied callback URL.

### Gateway behavior handled by this project

The system is designed for:

-   Callback delays.
-   Payment failures.
-   Duplicate callbacks.
-   `/charge` timeout/500 responses.
-   Delayed or missing OTP delivery.
-   Callback arriving before `/charge` returns.

### Important callback rule

The payment callback always returns HTTP `200`, including when the
callback has already been processed.

Duplicate callbacks are detected using an idempotency mechanism so that:

-   A payment is not created twice.
-   A booking is not confirmed twice.
-   Revenue is not counted twice.

------------------------------------------------------------------------

## Booking lifecycle

A normal booking follows:

``` text
AVAILABLE
    |
    | hold
    v
HELD
    |
    | payment succeeds
    v
BOOKED
```

If payment fails or the hold expires:

``` text
HELD
   |
   +---- payment FAILED ----+
   |                         |
   +---- TTL EXPIRED --------+
                             |
                             v
                         AVAILABLE
```

A successful payment callback:

``` text
Gateway
   |
   | SUCCEEDED callback
   v
Django callback endpoint
   |
   v
Verify event/idempotency
   |
   v
Confirm booking
   |
   v
BOOKED
```

------------------------------------------------------------------------

## Hold expiration

The hold duration is controlled by an environment variable:

``` text
HOLD_TTL_SECONDS
```

It is intentionally not hardcoded because judges will run the
application with a short TTL.

Example:

``` env
HOLD_TTL_SECONDS=30
```

Test scenario:

``` text
10:00:00  User A holds F12
10:00:30  Hold expires
10:00:31  F12 becomes AVAILABLE
10:00:35  User B successfully holds F12
```

This demonstrates that abandoned seats are automatically returned to the
available pool.

------------------------------------------------------------------------

## Tech stack

### Frontend

-   React
-   JavaScript/TypeScript
-   REST API integration
-   Responsive seat-map interface

### Backend

-   Python
-   Django
-   Django REST Framework

### Database

-   PostgreSQL
-   Database transactions
-   Row-level locking for seat contention

### Infrastructure

-   Docker
-   Docker Compose
-   GitHub Actions
-   Poridhi VM deployment

### Testing

-   Django/DRF tests
-   Concurrency/load testing
-   Gateway failure-mode testing
-   Hold-expiration testing

------------------------------------------------------------------------

## Data model

The core data model is intentionally simple.

### Movie

``` text
Movie
-----
id
title
description
duration
```

### Theatre

``` text
Theatre
-------
id
name
location
```

### Showtime

``` text
Showtime
--------
id
movie_id
theatre_id
start_time
```

### Seat

``` text
Seat
----
id
theatre_id
row
number
```

### ShowSeat

This is the central seat-state table.

``` text
ShowSeat
--------
id
showtime_id
seat_id
status
hold_id
hold_expires_at
booking_id
```

Possible states:

``` text
AVAILABLE
HELD
BOOKED
```

### Hold

``` text
Hold
----
id
showtime_id
seat_id
user/session reference
expires_at
status
```

### Booking

``` text
Booking
-------
id
showtime_id
seat_id
amount
status
payment_id
created_at
```

### Payment

``` text
Payment
-------
id
booking_id
gateway_payment_id
amount
status
created_at
updated_at
```

### Payment event / idempotency record

``` text
PaymentEvent
------------
id
event_id
payment_id
booking_ref
status
processed_at
```

The exact implementation may combine or separate these tables depending
on the final backend implementation.

------------------------------------------------------------------------

## API

The application exposes REST endpoints for browsing, seat maps, holds,
payments, callbacks, and bookings.

### Health

``` text
GET /health
```

Expected:

``` text
HTTP 200
```

The health endpoint must remain responsive even when the payment gateway
is unavailable.

### Movies

``` text
GET /api/movies/
```

### Showtimes

``` text
GET /api/showtimes/
```

### Seat map

``` text
GET /api/showtimes/{showtime_id}/seats/
```

**Exact judge request:**

``` bash
curl http://<DEPLOYED_URL>/api/showtimes/<SHOWTIME_ID>/seats/
```

> Update the path above to the exact implemented endpoint before
> submission.

### Hold a seat

``` text
POST /api/holds/
Content-Type: application/json
```

Example:

``` json
{
  "showtime_id": 1,
  "seat_id": 12
}
```

**Exact judge request:**

``` bash
curl -X POST http://<DEPLOYED_URL>/api/holds/ \
  -H "Content-Type: application/json" \
  -d '{"showtime_id":1,"seat_id":12}'
```

> Update the URL/body to the exact implemented API contract before
> submission.

### Payment

``` text
POST /api/payments/
```

### Payment callback

``` text
POST /api/payments/callback/
```

### Booking

``` text
GET /api/bookings/{booking_id}/
```

------------------------------------------------------------------------

## Frontend experience

The frontend focuses on the core booking path rather than unnecessary
visual complexity.

### Main flow

``` text
Movies
   ↓
Select Showtime
   ↓
Live Seat Map
   ↓
Select Seat
   ↓
Hold Seat
   ↓
Countdown
   ↓
Payment
   ↓
Payment Processing
   ↓
Booking Confirmation
```

### Seat states

The UI distinguishes:

``` text
Available
Held
Booked
Selected
```

The frontend does not make the final decision about seat availability.
The backend/database remains authoritative.

### Seat-map behavior

The seat map is fetched from the backend and reflects the current state
of seats for a particular showtime.

------------------------------------------------------------------------

## Testing and proof

The project is tested against the exact scenarios emphasized by the
contest.

### Scenario A --- One seat, many buyers

One seat is selected and 100 concurrent hold requests are fired at that
exact seat.

Required result:

  Metric                Result
  ------------------- --------
  Requests sent            100
  Successful holds           1
  Rejected requests         99
  Oversell count             0

The test also fetches the seat map afterward and verifies that the seat
is held exactly once.

### Scenario B --- Abandoned hold

``` text
1. Hold a seat.
2. Do not pay.
3. Use a short HOLD_TTL_SECONDS.
4. Wait for expiration.
5. Fetch the seat map.
6. Confirm the seat is AVAILABLE.
7. Attempt a new hold from another user.
8. Confirm the new hold succeeds.
```

### Payment failure

``` text
Hold
 ↓
Payment forced to fail
 ↓
Booking is not confirmed
 ↓
Seat is released according to the implemented booking policy
```

### Duplicate callback

``` text
Callback #1 → process
Callback #2 → recognize duplicate
Callback #3 → recognize duplicate
```

Expected:

``` text
Bookings created = 1
Payments created = 1
Revenue counted = once
```

### Gateway timeout

The backend must not block indefinitely waiting for the gateway and
should keep the rest of the application usable.

### Race callback

The system is tested with a callback arriving before the `/charge`
response completes.

------------------------------------------------------------------------

## Load testing

The contest bonus scenario ramps virtual users against the seat-map and
hold endpoints until the system begins to degrade.

The load generator is run separately from the application host.

The report focuses on:

-   p95 latency.
-   Error rate.
-   Breakpoint.
-   Observed bottleneck.
-   Explanation of why the bottleneck occurred.

Raw requests-per-second are not treated as the primary engineering
metric because the judging environment may use different VM resources.

------------------------------------------------------------------------

## Deployment

### Target deployment

The primary deployment target is:

**Poridhi VM + load balancer**

The deployment is designed to be reproducible from the repository.

### Deployed URL

``` text
https://<YOUR-DEPLOYED-URL>
```

Replace the placeholder before submission.

### Required health check

``` text
GET /health
```

Expected:

``` text
HTTP 200
```

The endpoint should respond in under one second and remain healthy even
when the gateway is unavailable.

------------------------------------------------------------------------

## CI/CD

GitHub Actions is used for automated validation and deployment.

### Pull request / push workflow

``` text
Developer
    |
    v
GitHub
    |
    v
CI
    |
    +--> Install dependencies
    |
    +--> Run tests
    |
    +--> Build/check
    |
    v
PASS / FAIL
```

### Deployment workflow

``` text
Push to default branch
          |
          v
       CI passes
          |
          v
     Build images
          |
          v
      Deploy
          |
          v
   Health verification
```

CI runs on pull requests and pushes to the default branch. CD runs on
pushes to the default branch.

------------------------------------------------------------------------

## Repository structure

``` text
.
├── backend/
│   ├── manage.py
│   ├── config/
│   ├── apps/
│   ├── requirements.txt
│   └── ...
│
├── frontend/
│   ├── src/
│   ├── public/
│   ├── package.json
│   └── ...
│
├── tests/
│   ├── concurrency/
│   ├── payment/
│   └── ...
│
├── docs/
│   ├── architecture.md
│   ├── architecture.png
│   ├── deployment.md
│   └── test-results.md
│
├── .github/
│   └── workflows/
│       ├── ci.yml
│       └── cd.yml
│
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── DECISIONS.md
└── README.md
```

Update this structure if the final repository differs.

------------------------------------------------------------------------

## Environment variables

Create a local `.env` from `.env.example`.

Example:

``` env
DEBUG=False

POSTGRES_DB=cinemaseat
POSTGRES_USER=cinemaseat
POSTGRES_PASSWORD=change_me
POSTGRES_HOST=postgres
POSTGRES_PORT=5432

HOLD_TTL_SECONDS=120

GATEWAY_URL=http://gateway:9000

DJANGO_SECRET_KEY=change_me
ALLOWED_HOSTS=localhost,127.0.0.1
```

### Required/important variables

  Variable              Required   Purpose
  --------------------- ---------- ---------------------------------
  `HOLD_TTL_SECONDS`    Yes        Configurable seat-hold duration
  `GATEWAY_URL`         Yes        Provided payment/OTP gateway
  `POSTGRES_DB`         Yes        PostgreSQL database
  `POSTGRES_USER`       Yes        PostgreSQL user
  `POSTGRES_PASSWORD`   Yes        PostgreSQL password
  `POSTGRES_HOST`       Yes        PostgreSQL hostname
  `POSTGRES_PORT`       Yes        PostgreSQL port
  `DJANGO_SECRET_KEY`   Yes        Django secret
  `ALLOWED_HOSTS`       Yes        Allowed Django hosts

Never commit real credentials or secrets to GitHub.

------------------------------------------------------------------------

## Local development

### Prerequisites

-   Git
-   Docker
-   Docker Compose
-   Node.js/npm or the project's selected React package manager
-   Python 3.x if running Django outside Docker

### Clone

``` bash
git clone <YOUR_PUBLIC_REPOSITORY_URL>
cd <YOUR_REPOSITORY>
```

### Environment

``` bash
cp .env.example .env
```

Edit `.env` as required.

### Start the complete stack

``` bash
docker compose up --build
```

The stack should start:

``` text
Frontend
Backend
PostgreSQL
Mock Gateway
```

No manual external dependency should be required for the core
application.

------------------------------------------------------------------------

## Docker setup

The Docker Compose stack contains the core application services:

``` yaml
services:
  frontend:
    ...

  backend:
    ...

  postgres:
    ...

  gateway:
    image: asifmahmoud414/mock-gateway:latest
    ports:
      - "9000:9000"
```

Start:

``` bash
docker compose up --build
```

Stop:

``` bash
docker compose down
```

Clean rebuild:

``` bash
docker compose down -v
docker compose up --build
```

The final repository must support:

``` bash
git clone <REPOSITORY>
cd <REPOSITORY>
docker compose up --build
```

from a clean clone without undocumented manual steps.

------------------------------------------------------------------------

## Judge verification

The following checks are intentionally documented so that the project
can be evaluated quickly.

### 1. Health

``` bash
curl http://<DEPLOYED_URL>/health
```

Expected:

``` text
HTTP 200
```

### 2. Fetch seat map

``` bash
curl http://<DEPLOYED_URL>/api/showtimes/<SHOWTIME_ID>/seats/
```

### 3. Hold a seat

``` bash
curl -X POST http://<DEPLOYED_URL>/api/holds/ \
  -H "Content-Type: application/json" \
  -d '{"showtime_id":1,"seat_id":12}'
```

### 4. Concurrency

Run 100 simultaneous hold requests against the **same showtime and same
seat**.

Expected:

``` text
Successful holds = 1
Rejected requests = 99
Oversell = 0
```

### 5. Hold expiration

Run with:

``` env
HOLD_TTL_SECONDS=20
```

Then:

``` text
Hold seat
   ↓
Do not pay
   ↓
Wait > 20 seconds
   ↓
Fetch seat map
   ↓
Seat becomes AVAILABLE
```

### 6. Payment force modes

The backend should be tested with the gateway's control headers:

``` text
X-Mock-Mode: deterministic
X-Mock-Force: fail
X-Mock-Force: duplicate
X-Mock-Force: timeout
X-Mock-Force: race
X-Mock-Force: success
```

These are test controls provided by the contest gateway.

------------------------------------------------------------------------

## Engineering decisions

The detailed engineering decisions are documented separately in
[`DECISIONS.md`](DECISIONS.md).

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

------------------------------------------------------------------------

## Known limitations

-   The application is optimized for the contest's core booking workflow
    rather than a full commercial cinema platform.
-   Cinema administration is not included.
-   Movies, theatres, showtimes, seats, and prices are pre-populated.
-   The frontend intentionally prioritizes functionality over visual
    polish.
-   The primary deployment uses a single backend service.
-   Advanced observability features such as distributed tracing may be
    omitted unless implemented as a bonus feature.
-   Authentication/authorization may be limited unless implemented in
    the final version.

Any limitation not implemented in the final build should be updated here
before submission.

------------------------------------------------------------------------

## Bonus features

If all required milestones are complete, the following can be
considered:

-   Fault isolation when the gateway is unavailable.
-   Structured logs with request IDs.
-   Metrics endpoint.
-   Distributed tracing.
-   Graceful degradation during a premiere-showtime traffic spike.
-   Nginx reverse proxy/load balancing.
-   Authentication and authorization.
-   Rate limiting.
-   Input validation.
-   Gateway callback signature verification.
-   AWS deployment.
-   Scenario C breakpoint/load testing.

Required functionality takes priority over bonus features.

------------------------------------------------------------------------

## Team contributions

| Member | Role | Primary Contribution |
|---|---|---|
| **Ashraful Islam** | Backend / Database | Django REST Framework, PostgreSQL, seat locking, booking, payment integration, callback handling, Docker |
| **Touhidul Islam** | Frontend | React interface, seat map, booking flow, API integration, payment/confirmation UI |
| **[Third Member]** | DevOps / QA / Documentation | CI/CD, deployment, concurrency testing, failure testing, README, architecture and documentation |
------------------------------------------------------------------------

## Attribution

-   React for the frontend.
-   Django and Django REST Framework for the backend.
-   PostgreSQL for persistent data and concurrency control.
-   Docker and Docker Compose for containerization.
-   GitHub Actions for CI/CD.
-   The contest-provided mock gateway for payment and OTP behavior.
-   Any additional open-source packages used in the final implementation
    should be listed here.

------------------------------------------------------------------------

## Submission checklist

Before submission, verify:

-   [ ] Repository is public.
-   [ ] README.md is complete.
-   [ ] DECISIONS.md is complete.
-   [ ] Architecture diagram is included.
-   [ ] Exact seat-map request is documented.
-   [ ] Exact seat-hold request is documented.
-   [ ] `GET /health` returns HTTP 200.
-   [ ] `HOLD_TTL_SECONDS` is read from the environment.
-   [ ] `docker compose up` works from a clean clone.
-   [ ] Provided gateway is integrated.
-   [ ] Payment callbacks are asynchronous.
-   [ ] Duplicate callbacks are idempotent.
-   [ ] Hold expiration works.
-   [ ] 100 concurrent requests for one seat produce exactly one
    successful hold.
-   [ ] Oversell count is zero.
-   [ ] Deployment URL is reachable.
-   [ ] CI runs successfully.
-   [ ] CD/deployment workflow works.
-   [ ] Test results are documented.
-   [ ] No secrets are committed.
-   [ ] Code is frozen before final submission.

------------------------------------------------------------------------

## Final objective

CinemaSeat is built around one engineering promise:

> **When everyone wants the same seat, exactly one person gets it ---
> and the system remains reliable even when payment services are slow or
> fail.**

The project prioritizes **correctness, concurrency safety, reliable
payment handling, containerized deployment, and measurable proof** over
unnecessary features or UI complexity.
