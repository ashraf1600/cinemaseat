import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";

export default function ShowtimesPage() {
  const { movieId } = useParams();
  const [showtimes, setShowtimes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    api
      .getShowtimes(movieId)
      .then(setShowtimes)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [movieId]);

  return (
    <div className="max-w-5xl mx-auto px-6 pt-12 pb-16">
      <Link
        to="/"
        className="font-mono text-xs tracking-widest uppercase inline-flex items-center gap-2 mb-8 transition-colors hover:text-[color:var(--gold)]"
        style={{ color: "var(--muted)" }}
      >
        &larr; Back to lineup
      </Link>

      <p
        className="font-mono text-xs tracking-[0.3em] uppercase mb-3"
        style={{ color: "var(--gold)" }}
      >
        Choose a time
      </p>
      <h1 className="font-display text-5xl sm:text-6xl marquee-glow mb-10">
        Showtimes
      </h1>

      {loading && (
        <p className="font-mono text-sm" style={{ color: "var(--muted)" }}>
          Loading showtimes...
        </p>
      )}
      {error && (
        <p className="font-mono text-sm" style={{ color: "var(--rose)" }}>
          {error}
        </p>
      )}

      <div className="grid sm:grid-cols-2 gap-4">
        {showtimes.map((show) => {
          const date = new Date(show.starts_at);
          return (
            <Link
              key={show.id}
              to={`/showtimes/${show.id}/seats`}
              className="group flex items-center justify-between rounded-xl px-6 py-5 border transition-all duration-300 hover:-translate-y-0.5"
              style={{
                background: "var(--surface)",
                borderColor: "rgba(242,183,5,0.15)",
              }}
            >
              <div>
                <p className="font-display text-3xl group-hover:text-[color:var(--gold)] transition-colors">
                  {date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                </p>
                <p className="text-sm mt-1" style={{ color: "var(--muted)" }}>
                  {date.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" })}
                </p>
              </div>
              <div className="text-right">
                <p className="font-mono text-xs" style={{ color: "var(--muted)" }}>
                  from
                </p>
                <p className="font-display text-2xl" style={{ color: "var(--gold)" }}>
                  ৳{show.base_price}
                </p>
              </div>
            </Link>
          );
        })}
      </div>

      {!loading && showtimes.length === 0 && !error && (
        <p style={{ color: "var(--muted)" }}>No showtimes found.</p>
      )}
    </div>
  );
}