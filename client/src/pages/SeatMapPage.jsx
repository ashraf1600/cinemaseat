import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import SeatGrid from "../components/SeatGrid";

export default function SeatMapPage() {
  const { showtimeId } = useParams();
  const navigate = useNavigate();

  const [seats, setSeats] = useState([]);
  const [selectedSeatIds, setSelectedSeatIds] = useState([]);
  const [phone, setPhone] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [holding, setHolding] = useState(false);

  async function loadSeats() {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getSeats(showtimeId);
      setSeats(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function pollSeats() {
    try {
      const data = await api.getSeats(showtimeId);
      setSeats(data);
    } catch (err) {
      // Silent fail on polling — don't show loading or error
    }
  }

  useEffect(() => {
    loadSeats();
    const interval = setInterval(pollSeats, 5000);
    return () => clearInterval(interval);
  }, [showtimeId]);

  function toggleSeat(seatId) {
    setSelectedSeatIds((prev) =>
      prev.includes(seatId) ? prev.filter((id) => id !== seatId) : [...prev, seatId]
    );
  }

  async function handleHold() {
    if (selectedSeatIds.length === 0) {
      setError("Select at least one seat.");
      return;
    }
    if (!phone.trim()) {
      setError("Enter a phone number.");
      return;
    }

    setHolding(true);
    setError(null);
    try {
      const booking = await api.holdSeats({
        showtimeId: Number(showtimeId),
        seatIds: selectedSeatIds,
        phone: phone.trim(),
      });
      navigate(`/bookings/${booking.booking_id}`);
    } catch (err) {
      setError(err.message);
      loadSeats();
      setSelectedSeatIds([]);
    } finally {
      setHolding(false);
    }
  }

  const selectedSeats = seats.filter((s) => selectedSeatIds.includes(s.id));
 const total = selectedSeats.reduce((sum, s) => sum + Number(s.price), 0);

  return (
    <div className="max-w-4xl mx-auto px-6 pt-12 pb-24">
      <p
        className="font-mono text-xs tracking-[0.3em] uppercase mb-3"
        style={{ color: "var(--gold)" }}
      >
        Step 1 of 3
      </p>
      <h1 className="font-display text-5xl sm:text-6xl marquee-glow mb-10">
        Take your seats.
      </h1>

      {loading && (
        <p className="font-mono text-sm" style={{ color: "var(--muted)" }}>
          Loading seat map...
        </p>
      )}

      {!loading && (
        <>
          <SeatGrid
            seats={seats}
            selectedSeatIds={selectedSeatIds}
            onToggleSeat={toggleSeat}
          />

          {/* Sticky checkout bar */}
          <div
            className="rounded-xl p-6 border mt-4"
            style={{ background: "var(--surface)", borderColor: "rgba(242,183,5,0.15)" }}
          >
            <div className="flex flex-wrap items-end justify-between gap-6 mb-5">
              <div>
                <p className="font-mono text-xs uppercase tracking-wider mb-1" style={{ color: "var(--muted)" }}>
                  Selected
                </p>
                <p className="font-display text-2xl">
                  {selectedSeats.length > 0
                    ? selectedSeats.map((s) => s.label).join(", ")
                    : "—"}
                </p>
              </div>
              <div className="text-right">
                <p className="font-mono text-xs uppercase tracking-wider mb-1" style={{ color: "var(--muted)" }}>
                  Total
                </p>
                <p className="font-display text-3xl" style={{ color: "var(--gold)" }}>
                  ৳{total}
                </p>
              </div>
            </div>

            <label className="block mb-4">
              <span className="font-mono text-xs uppercase tracking-wider block mb-2" style={{ color: "var(--muted)" }}>
                Phone number
              </span>
              <input
                type="tel"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="+8801XXXXXXXXX"
                className="w-full rounded-lg px-4 py-3 outline-none border transition-colors focus:border-[color:var(--gold)]"
                style={{
                  background: "var(--bg)",
                  borderColor: "rgba(182,166,194,0.2)",
                  color: "var(--ink)",
                }}
              />
            </label>

            {error && (
              <p className="font-mono text-sm mb-4" style={{ color: "var(--rose)" }}>
                {error}
              </p>
            )}

            <button
              type="button"
              onClick={handleHold}
              disabled={holding}
              className="w-full rounded-lg py-4 font-display text-2xl tracking-wide transition-transform hover:scale-[1.01] disabled:opacity-50 disabled:hover:scale-100"
              style={{ background: "var(--gold)", color: "var(--bg)" }}
            >
              {holding ? "HOLDING..." : "HOLD MY SEATS"}
            </button>
          </div>
        </>
      )}
    </div>
  );
}