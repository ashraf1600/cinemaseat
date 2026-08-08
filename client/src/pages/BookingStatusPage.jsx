import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";

export default function BookingStatusPage() {
  const { bookingId } = useParams();

  const [booking, setBooking] = useState(null);
  const [otpCode, setOtpCode] = useState("");
  const [otpSent, setOtpSent] = useState(false);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const pollRef = useRef(null);

  useEffect(() => {
    refreshBooking();
    return () => stopPolling();
  }, [bookingId]);

  async function refreshBooking() {
    try {
      const data = await api.getBooking(bookingId);
      setBooking(data);
      // The live backend returns the booking's lifecycle directly
      // (`HELD` / `PAID` / `EXPIRED` / `CANCELLED`); ``payment.status``
      // exists in the mock but not over the wire. Poll only while the
      // booking is still HELD (i.e. payment is in flight or pending).
      if (data.status === "PAID" || data.status === "CANCELLED" || data.status === "EXPIRED") {
        stopPolling();
      }
    } catch (err) {
      setError(err.message);
    }
  }

  function startPolling() {
    stopPolling();
    // Poll every 1 second during payment for faster updates
    pollRef.current = setInterval(refreshBooking, 1000);
  }

  function stopPolling() {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  async function handleSendOtp() {
    setBusy(true);
    setError(null);
    try {
      await api.sendOtp(bookingId);
      setOtpSent(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleVerifyOtp() {
    if (!otpCode.trim()) {
      setError("Enter the OTP code.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.verifyOtp(bookingId, otpCode.trim());
      await refreshBooking();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function handlePay() {
    setBusy(true);
    setError(null);
    try {
      await api.startPayment(bookingId);
      startPolling();
      await refreshBooking();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (!booking) {
    return (
      <div className="max-w-xl mx-auto px-6 pt-12">
        <p className="font-mono text-sm" style={{ color: "var(--muted)" }}>
          Loading booking...
        </p>
        {error && (
          <p className="font-mono text-sm mt-2" style={{ color: "var(--rose)" }}>
            {error}
          </p>
        )}
      </div>
    );
  }

  // The live backend reports booking state in `booking.status`. Map
  // "PAID" to the confirmed-on-screen equivalent ("SUCCEEDED") so the
  // existing render tree can stay generic.
  const isConfirmed = booking.status === "PAID";
  const paymentStatus = isConfirmed ? "SUCCEEDED" : booking.status;

  return (
    <div className="max-w-xl mx-auto px-6 pt-12 pb-24">
      <p
        className="font-mono text-xs tracking-[0.3em] uppercase mb-3"
        style={{ color: "var(--gold)" }}
      >
        {isConfirmed ? "You're all set" : "Step 2 of 3"}
      </p>
      <h1 className="font-display text-5xl marquee-glow mb-8">
        {isConfirmed ? "Enjoy the show." : "Almost there."}
      </h1>

      {/* Ticket stub */}
      <div className="ticket-stub rounded-xl p-6 pr-28 mb-6 relative">
        <p className="font-mono text-xs uppercase tracking-wider mb-1" style={{ color: "var(--muted)" }}>
          Booking Ref
        </p>
        <p className="font-display text-3xl mb-4" style={{ color: "var(--gold)" }}>
          {booking.booking_id || bookingId}
        </p>
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <p className="font-mono text-xs uppercase tracking-wider mb-1" style={{ color: "var(--muted)" }}>
              Seats
            </p>
            <p>{booking.seats?.map((s) => s.label).join(", ") || "—"}</p>
          </div>
          <div>
            <p className="font-mono text-xs uppercase tracking-wider mb-1" style={{ color: "var(--muted)" }}>
              Status
            </p>
            <p style={{ color: isConfirmed ? "var(--emerald)" : "var(--ink)" }}>
              {booking.status}
            </p>
          </div>
          {booking.expires_at && !isConfirmed && (
            <div className="col-span-2">
              <p className="font-mono text-xs uppercase tracking-wider mb-1" style={{ color: "var(--muted)" }}>
                Hold expires
              </p>
              <p>{new Date(booking.expires_at).toLocaleTimeString()}</p>
            </div>
          )}
        </div>
      </div>

      {error && (
        <p className="font-mono text-sm mb-4" style={{ color: "var(--rose)" }}>
          {error}
        </p>
      )}

      {/* Step: OTP — only show while the booking is still HELD. Once
          the booking is PAID the OTP step has already happened (the
          webhook flips it). */}
      {booking.status === "HELD" && (
        <div
          className="rounded-xl p-6 border mb-6"
          style={{ background: "var(--surface)", borderColor: "rgba(242,183,5,0.15)" }}
        >
          <h2 className="font-display text-2xl mb-4">Verify your phone</h2>
          {!otpSent ? (
            <button
              type="button"
              onClick={handleSendOtp}
              disabled={busy}
              className="rounded-lg px-6 py-3 font-display text-lg tracking-wide transition-transform hover:scale-[1.02] disabled:opacity-50"
              style={{ background: "var(--gold)", color: "var(--bg)" }}
            >
              SEND CODE
            </button>
          ) : (
            <div className="flex gap-3">
              <input
                type="text"
                value={otpCode}
                onChange={(e) => setOtpCode(e.target.value)}
                placeholder="0000"
                className="flex-1 rounded-lg px-4 py-3 outline-none border font-mono text-lg tracking-[0.3em] focus:border-[color:var(--gold)]"
                style={{ background: "var(--bg)", borderColor: "rgba(182,166,194,0.2)", color: "var(--ink)" }}
              />
              <button
                type="button"
                onClick={handleVerifyOtp}
                disabled={busy}
                className="rounded-lg px-6 py-3 font-display text-lg tracking-wide transition-transform hover:scale-[1.02] disabled:opacity-50"
                style={{ background: "var(--gold)", color: "var(--bg)" }}
              >
                VERIFY
              </button>
            </div>
          )}
          <p className="font-mono text-xs mt-3" style={{ color: "var(--muted)" }}>
            Delivery can be delayed — resend if nothing arrives.
          </p>
        </div>
      )}

      {/* Step: Payment */}
      <div
        className="rounded-xl p-6 border"
        style={{ background: "var(--surface)", borderColor: "rgba(242,183,5,0.15)" }}
      >
        <h2 className="font-display text-2xl mb-4">Payment</h2>
        <p className="font-mono text-xs uppercase tracking-wider mb-4" style={{ color: "var(--muted)" }}>
          Status: <span style={{ color: "var(--ink)" }}>{paymentStatus || "Not started"}</span>
        </p>

        {booking.status === "HELD" && (
          <button
            type="button"
            onClick={handlePay}
            disabled={busy}
            className="w-full rounded-lg py-4 font-display text-2xl tracking-wide transition-transform hover:scale-[1.01] disabled:opacity-50 disabled:hover:scale-100"
            style={{ background: "var(--emerald)", color: "var(--bg)" }}
          >
            {busy ? "PROCESSING..." : "PAY NOW"}
          </button>
        )}

        {booking.status === "HELD" && busy && (
          <p className="font-mono text-xs mt-3" style={{ color: "var(--muted)" }}>
            Confirming with the gateway — up to 15 seconds.
          </p>
        )}

        {booking.status === "EXPIRED" && (
          <p className="font-mono text-sm mt-3" style={{ color: "var(--rose)" }}>
            Your hold expired before payment was confirmed. Please try again.
          </p>
        )}

        {isConfirmed && (
          <p className="font-display text-2xl mt-2" style={{ color: "var(--emerald)" }}>
            Payment confirmed. See you at the movies!
          </p>
        )}
      </div>
    </div>
  );
}