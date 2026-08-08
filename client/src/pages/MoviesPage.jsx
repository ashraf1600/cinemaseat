import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";

export default function MoviesPage() {
  const [movies, setMovies] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    api
      .getMovies()
      .then(setMovies)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div style={{ minHeight: "100vh", background: "linear-gradient(135deg, #0f0f1e 0%, #1a0a2e 100%)" }}>
      {/* Animated styles */}
      <style>{`
        @keyframes slideDown {
          from {
            opacity: 0;
            transform: translateY(-30px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }
        @keyframes fadeInUp {
          from {
            opacity: 0;
            transform: translateY(40px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }
        @keyframes glow-pulse {
          0%, 100% { box-shadow: 0 0 20px rgba(242, 183, 5, 0.3); }
          50% { box-shadow: 0 0 40px rgba(242, 183, 5, 0.6); }
        }
        .animate-slide-down {
          animation: slideDown 0.8s ease-out;
        }
        .animate-fade-up {
          animation: fadeInUp 0.8s ease-out;
        }
        .glow-pulse {
          animation: glow-pulse 3s ease-in-out infinite;
        }
        .movie-card {
          animation: fadeInUp 0.8s ease-out backwards;
          transition: all 0.5s cubic-bezier(0.34, 1.56, 0.64, 1);
        }
        .movie-card:hover {
          transform: translateY(-12px) scale(1.02);
        }
        .movie-card:nth-child(1) { animation-delay: 0.1s; }
        .movie-card:nth-child(2) { animation-delay: 0.3s; }
        .movie-card:nth-child(3) { animation-delay: 0.5s; }
      `}</style>

      {/* Hero Section */}
      <section className="max-w-5xl mx-auto px-6 pt-20 pb-16">
        <div className="animate-slide-down">
          <p
            className="font-mono text-xs tracking-[0.3em] uppercase mb-4 glow-pulse inline-block"
            style={{ color: "var(--gold)" }}
          >
            🎬 Tonight's Lineup
          </p>
        </div>
        <div className="animate-slide-down" style={{ animationDelay: "0.2s" }}>
          <h1 
            className="font-display text-7xl sm:text-8xl leading-[0.95] mb-6"
            style={{
              background: "linear-gradient(135deg, #fcd34d 0%, #f97316 50%, #ec4899 100%)",
              backgroundClip: "text",
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
            }}
          >
            Pick your picture.
          </h1>
        </div>
        <div className="animate-fade-up" style={{ animationDelay: "0.4s" }}>
          <p className="text-lg max-w-2xl" style={{ color: "var(--muted)" }}>
            ✨ Real seats, live status, zero oversell. Book your perfect cinematic experience in under a minute.
          </p>
        </div>
      </section>

      <div className="film-strip max-w-5xl mx-auto" />

      {/* Movie Grid Section */}
      <section className="max-w-5xl mx-auto px-6 py-16">
        {loading && (
          <div className="animate-fade-up text-center">
            <div className="inline-block">
              <div
                className="w-8 h-8 border-3 rounded-full animate-spin"
                style={{ borderColor: "var(--gold)", borderTopColor: "transparent" }}
              />
            </div>
            <p className="font-mono text-sm mt-3" style={{ color: "var(--muted)" }}>
              Loading cinematic wonders...
            </p>
          </div>
        )}
        {error && (
          <p className="font-mono text-sm text-center" style={{ color: "var(--rose)" }}>
            {error}
          </p>
        )}

        {!loading && movies.length > 0 && (
          <div className="grid sm:grid-cols-2 gap-6">
            {movies.map((movie, i) => (
              <Link
                key={movie.id}
                to={`/movies/${movie.id}/showtimes`}
                className="movie-card group relative overflow-hidden rounded-2xl p-8 border"
                style={{
                  background: `linear-gradient(135deg, ${
                    i % 2 === 0 
                      ? "rgba(168, 85, 247, 0.15)" 
                      : "rgba(59, 130, 246, 0.15)"
                  } 0%, rgba(20, 11, 26, 0.5) 100%)`,
                  borderColor: "rgba(242, 183, 5, 0.25)",
                  backdropFilter: "blur(10px)",
                }}
              >
                {/* Animated gradient overlay on hover */}
                <div
                  className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-500"
                  style={{
                    background: `linear-gradient(135deg, ${
                      i % 2 === 0 
                        ? "rgba(168, 85, 247, 0.3)" 
                        : "rgba(59, 130, 246, 0.3)"
                    } 0%, rgba(242, 183, 5, 0.1) 100%)`,
                  }}
                />

                {/* Content wrapper */}
                <div className="relative z-10">
                  {/* Movie number with gradient */}
                  <div className="flex items-center gap-3 mb-4">
                    <span
                      className="font-mono text-sm font-bold px-3 py-1 rounded-full"
                      style={{
                        background: `linear-gradient(135deg, var(--gold), ${
                          i % 2 === 0 ? "#ec4899" : "#3b82f6"
                        })`,
                        color: "var(--bg)",
                      }}
                    >
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <span className="text-2xl">🎥</span>
                  </div>

                  {/* Title with enhanced styling */}
                  <h2
                    className="font-display text-5xl sm:text-6xl mb-3 leading-tight group-hover:scale-105 transition-transform duration-500 origin-left"
                    style={{
                      background: `linear-gradient(135deg, var(--gold), ${
                        i % 2 === 0 ? "#ec4899" : "#3b82f6"
                      })`,
                      backgroundClip: "text",
                      WebkitBackgroundClip: "text",
                      WebkitTextFillColor: "transparent",
                    }}
                  >
                    {movie.title}
                  </h2>

                  {/* Duration badge */}
                  <div className="flex items-center gap-2 mt-4">
                    <span className="text-xl">⏱️</span>
                    <p className="text-sm font-mono" style={{ color: "var(--muted)" }}>
                      {movie.duration_minutes} minutes of pure cinema
                    </p>
                  </div>
                </div>

                {/* Decorative line at bottom */}
                <div
                  className="absolute inset-x-0 bottom-0 h-1 scale-x-0 group-hover:scale-x-100 transition-transform duration-500 origin-left"
                  style={{
                    background: `linear-gradient(90deg, var(--gold), ${
                      i % 2 === 0 ? "#ec4899" : "#3b82f6"
                    }, transparent)`,
                  }}
                />
              </Link>
            ))}
          </div>
        )}

        {!loading && movies.length === 0 && !error && (
          <p className="text-center" style={{ color: "var(--muted)" }}>
            No movies available right now. Check back soon! 🍿
          </p>
        )}
      </section>
    </div>
  );
}