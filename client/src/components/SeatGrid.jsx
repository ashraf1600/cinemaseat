const STATUS_CONFIG = {
  AVAILABLE: { bg: "rgba(52,211,153,0.15)", border: "#34d399", text: "#34d399", clickable: true },
  SELECTED: { bg: "#f2b705", border: "#f2b705", text: "#140b1a", clickable: true },
  HELD: { bg: "rgba(182,166,194,0.08)", border: "rgba(182,166,194,0.25)", text: "#b6a6c2", clickable: false },
  BOOKED: { bg: "rgba(232,69,92,0.1)", border: "rgba(232,69,92,0.3)", text: "#e8455c", clickable: false },
};

export default function SeatGrid({ seats, selectedSeatIds, onToggleSeat }) {
  if (!seats || seats.length === 0) {
    return (
      <p className="font-mono text-sm" style={{ color: "var(--muted)" }}>
        No seats found for this showtime.
      </p>
    );
  }

  return (
    <div>
      {/* Screen indicator */}
      <div className="mb-10 text-center">
        <div
          className="h-1.5 rounded-full mx-auto mb-2 max-w-md"
          style={{
            background: "linear-gradient(90deg, transparent, var(--gold), transparent)",
            boxShadow: "0 8px 24px rgba(242,183,5,0.25)",
          }}
        />
        <p className="font-mono text-xs tracking-[0.3em] uppercase" style={{ color: "var(--muted)" }}>
          Screen
        </p>
      </div>

      <div className="flex flex-wrap justify-center gap-3 mb-10">
        {seats.map((seat) => {
          const isSelected = selectedSeatIds.includes(seat.id);
          const key = seat.status === "AVAILABLE" && isSelected ? "SELECTED" : seat.status;
          const cfg = STATUS_CONFIG[key];

          return (
            <button
              key={seat.id}
              type="button"
              disabled={!cfg.clickable}
              onClick={() => cfg.clickable && onToggleSeat(seat.id)}
              className="w-16 h-16 rounded-lg flex flex-col items-center justify-center font-display text-lg border-2 transition-all duration-150 hover:scale-105 disabled:hover:scale-100"
              style={{
                background: cfg.bg,
                borderColor: cfg.border,
                color: cfg.text,
                cursor: cfg.clickable ? "pointer" : "not-allowed",
              }}
              title={`${seat.label} — ${seat.status} — ৳${seat.price}`}
            >
              {seat.label}
            </button>
          );
        })}
      </div>

      <div className="flex flex-wrap justify-center gap-6 font-mono text-xs">
        <Legend color="#34d399" label="Available" />
        <Legend color="#f2b705" label="Selected" />
        <Legend color="rgba(182,166,194,0.6)" label="Held" />
        <Legend color="#e8455c" label="Booked" />
      </div>
    </div>
  );
}

function Legend({ color, label }) {
  return (
    <div className="flex items-center gap-2" style={{ color: "var(--muted)" }}>
      <span className="w-3 h-3 rounded" style={{ background: color }} />
      {label.toUpperCase()}
    </div>
  );
}