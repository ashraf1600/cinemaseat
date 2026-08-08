// Set to false once your teammate's Django backend is running and you've
// confirmed the real endpoints match these shapes.
const USE_MOCK = false;

// Use a relative URL so the Vite dev-server proxy (see vite.config.js)
// forwards `/api/*` to Django during development. To hit a backend on a
// different host (e.g. a deployed staging server), set VITE_API_BASE_URL
// in `client/.env.local` to e.g. "https://staging.example.com/api".
const BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api";

// ---------- Mock data ----------

const mockMovies = [
  { id: 1, title: "Dune: Part Three", duration_minutes: 166 },
  { id: 2, title: "The Last Reel", duration_minutes: 128 },
];

const mockShowtimes = {
  1: [
    { id: 7, movie_id: 1, theatre_id: 1, starts_at: "2026-08-08T18:00:00Z", base_price: 450 },
    { id: 8, movie_id: 1, theatre_id: 1, starts_at: "2026-08-08T21:00:00Z", base_price: 450 },
  ],
  2: [
    { id: 9, movie_id: 2, theatre_id: 1, starts_at: "2026-08-08T19:30:00Z", base_price: 400 },
  ],
};

let mockSeats = [
  { id: 12, label: "F12", status: "AVAILABLE", price: 450 },
  { id: 13, label: "F13", status: "HELD", price: 450 },
  { id: 14, label: "F14", status: "BOOKED", price: 450 },
  { id: 15, label: "F15", status: "AVAILABLE", price: 450 },
  { id: 16, label: "F16", status: "AVAILABLE", price: 450 },
];

// Mock bookings with localStorage persistence
function getMockBookings() {
  const stored = localStorage.getItem("mockBookings");
  return stored ? JSON.parse(stored) : {};
}

function saveMockBookings(bookings) {
  localStorage.setItem("mockBookings", JSON.stringify(bookings));
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function makeBookingId() {
  return "bk_" + Math.random().toString(36).slice(2, 8);
}

// ---------- Real request helper (used when USE_MOCK is false) ----------

async function request(path, options = {}) {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  let data = null;
  try {
    data = await res.json();
  } catch {
    // some responses (like the webhook) may not return JSON
  }

  if (!res.ok) {
    const message =
      data?.error?.detail || data?.detail || `Request failed (${res.status})`;
    const error = new Error(message);
    error.status = res.status;
    error.data = data;
    throw error;
  }

  return data;
}

// ---------- Public API (same shape whether mocked or real) ----------

export const api = {
  getMovies: async () => {
    if (USE_MOCK) {
      await delay(300);
      return mockMovies;
    }
    return request("/movies/");
  },

  getShowtimes: async (movieId) => {
    if (USE_MOCK) {
      await delay(300);
      return mockShowtimes[movieId] || [];
    }
    return request(movieId ? `/showtimes/?movie_id=${movieId}` : "/showtimes/");
  },

  getSeats: async (showtimeId) => {
    if (USE_MOCK) {
      await delay(300);
      return mockSeats;
    }
    return request(`/showtimes/${showtimeId}/seats/`);
  },

  holdSeats: async ({ showtimeId, seatIds, phone }) => {
    if (USE_MOCK) {
      await delay(400);
      const unavailable = seatIds.some((id) => {
        const seat = mockSeats.find((s) => s.id === id);
        return !seat || seat.status !== "AVAILABLE";
      });
      if (unavailable) {
        const error = new Error("One or more seats are no longer available.");
        error.status = 409;
        throw error;
      }
      mockSeats = mockSeats.map((s) =>
        seatIds.includes(s.id) ? { ...s, status: "HELD" } : s
      );
      const bookingId = makeBookingId();
      const booking = {
        booking_id: bookingId,
        status: "HELD",
        expires_at: new Date(Date.now() + 5 * 60 * 1000).toISOString(),
        seats: mockSeats.filter((s) => seatIds.includes(s.id)),
        phone,
        payment: { status: null },
      };
      const bookings = getMockBookings();
      bookings[bookingId] = booking;
      saveMockBookings(bookings);
      return booking;
    }
    return request("/bookings/hold/", {
      method: "POST",
      body: JSON.stringify({ showtime_id: showtimeId, seat_ids: seatIds, phone }),
    });
  },

  sendOtp: async (bookingId) => {
    if (USE_MOCK) {
      await delay(300);
      return { sent: true };
    }
    return request(`/bookings/${bookingId}/otp/send/`, { method: "POST" });
  },

  verifyOtp: async (bookingId, code) => {
    if (USE_MOCK) {
      await delay(300);
      if (code !== "0000") {
        const error = new Error("Invalid OTP code (use 0000 in mock mode).");
        throw error;
      }
      const bookings = getMockBookings();
      bookings[bookingId].status = "VERIFIED";
      saveMockBookings(bookings);
      return { verified: true };
    }
    return request(`/bookings/${bookingId}/otp/verify/`, {
      method: "POST",
      body: JSON.stringify({ code }),
    });
  },

  startPayment: async (bookingId) => {
    if (USE_MOCK) {
      const bookings = getMockBookings();
      const booking = bookings[bookingId];
      booking.payment.status = "PROCESSING";
      saveMockBookings(bookings);
      // Simulate the gateway's documented 2-15s delay + 10% failure rate.
      delay(2000).then(() => {
        const bookings = getMockBookings();
        const booking = bookings[bookingId];
        const failed = Math.random() < 0.1;
        booking.payment.status = failed ? "FAILED" : "SUCCEEDED";
        booking.status = failed ? "VERIFIED" : "CONFIRMED";
        if (!failed) {
          mockSeats = mockSeats.map((s) =>
            booking.seats.some((bs) => bs.id === s.id)
              ? { ...s, status: "BOOKED" }
              : s
          );
        }
        saveMockBookings(bookings);
      });
      return { started: true };
    }
    return request(`/bookings/${bookingId}/pay/`, { method: "POST" });
  },

  getBooking: async (bookingId) => {
    if (USE_MOCK) {
      await delay(200);
      const bookings = getMockBookings();
      const booking = bookings[bookingId];
      if (!booking) {
        const error = new Error("Booking not found.");
        error.status = 404;
        throw error;
      }
      return booking;
    }
    return request(`/bookings/${bookingId}/`);
  },
};