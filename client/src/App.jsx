import { Routes, Route, Link } from "react-router-dom";
import MoviesPage from "./pages/MoviesPage";
import ShowtimesPage from "./pages/ShowtimesPage";
import SeatMapPage from "./pages/SeatMapPage";
import BookingStatusPage from "./pages/BookingStatusPage";

export default function App() {
  return (
    <div className="min-h-screen" style={{ background: "var(--bg)" }}>
      <header className="border-b border-white/5 sticky top-0 z-10 backdrop-blur bg-[color:var(--bg)]/80">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center gap-3">
          <Link to="/" className="flex items-center gap-2">
            <span
              className="font-display text-3xl marquee-glow"
              style={{ color: "var(--gold)" }}
            >
              CINEMA
            </span>
            <span className="font-display text-3xl" style={{ color: "var(--ink)" }}>
              SEAT
            </span>
          </Link>
        </div>
        <div className="film-strip" />
      </header>

      <main>
        <Routes>
          <Route path="/" element={<MoviesPage />} />
          <Route path="/movies/:movieId/showtimes" element={<ShowtimesPage />} />
          <Route path="/showtimes/:showtimeId/seats" element={<SeatMapPage />} />
          <Route path="/bookings/:bookingId" element={<BookingStatusPage />} />
        </Routes>
      </main>
    </div>
  );
}