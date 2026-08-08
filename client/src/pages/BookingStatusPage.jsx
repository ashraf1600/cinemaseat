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
  const [codeCopied, setCodeCopied] = useState(false);
  const pollRef = useRef(null);
  // Tracks the last code we autofilled so we don't clobber the user
  // typing into the input by re-applying the delivered code on every
  // poll. We compare against this ref inside refreshBooking().
  const otpCodeRef = useRef("");

  useEffect(() => {
    refreshBooking();
    // Always poll every 2s while the booking is still HELD — the
    // gateway may push the OTP delivery receipt at any time during
    // this window, so we poll continuously to autofill the code and
    // to surface the payment confirmation.
    pollRef.current = setInterval(refreshBooking, 2000);
    return () => stopPolling();
  }, [bookingId]);

  async function refreshBooking() {
    try {
      const data = await api.getBooking(bookingId);
      setBooking(data);
      // Autofill the OTP code as soon as the webhook delivers it.
      // ``last_delivered_code`` is set by the backend only when the
      // gateway has actually pushed the code via /api/webhooks/otp/.
      // If the user has already started typing (the sentinel is set
      // in onChange), we leave their input alone.
      if (
        data.last_delivered_code &&
        data.last_delivered_code !== otpCodeRef.current &&
        otpCodeRef.current !== "__USER_TYPING__"
      ) {
        otpCodeRef.current = data.last_delivered_code;
        setOtpCode(data.last_delivered_code);
      }
      // The live backend returns the booking's lifecycle directly
      // (`HELD` / `PAID` / `EXPIRED` / `CANCELLED`); ``payment.status``
      // exists in the mock but not over the wire. Stop polling once
      // the booking is in a terminal state.
      if (data.status === "PAID" || data.status === "CANCELLED" || data.status === "EXPIRED") {
        stopPolling();
      }
    } catch (err) {
      setError(err.message);
    }
  }

  function startPolling() {
    // Kept for backwards compatibility with handlePay — we now poll
    // for the entire HELD window, so this is a no-op.
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
            <>
              {booking.last_delivered_code ? (
                <div
                  className="rounded-lg px-4 py-3 mb-3 border"
                  style={{
                    background: "rgba(16,185,129,0.08)",
                    borderColor: "rgba(16,185,129,0.35)",
                  }}
                >
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p
                        className="font-mono text-[10px] uppercase tracking-[0.25em]"
                        style={{ color: "var(--muted)" }}
                      >
                        Code delivered
                      </p>
                      <p
                        className="font-mono text-2xl tracking-[0.4em]"
                        style={{ color: "var(--emerald)" }}
                      >
                        {booking.last_delivered_code}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={async () => {
                        try {
                          await navigator.clipboard.writeText(
                            booking.last_delivered_code
                          );
                          setCodeCopied(true);
                          setTimeout(() => setCodeCopied(false), 2000);
                        } catch {
                          // Clipboard may be unavailable in some
                          // sandboxed contexts — fall back to manual.
                        }
                      }}
                      className="rounded-md px-3 py-1.5 font-mono text-[11px] uppercase tracking-wider border transition-colors"
                      style={{
                        borderColor: "rgba(16,185,129,0.35)",
                        color: "var(--emerald)",
                      }}
                    >
                      {codeCopied ? "Copied" : "Copy"}
                    </button>
                  </div>
                  {booking.last_delivered_at && (
                    <p
                      className="font-mono text-[10px] mt-1"
                      style={{ color: "var(--muted)" }}
                    >
                      Delivered at{" "}
                      {new Date(booking.last_delivered_at).toLocaleTimeString()}
                    </p>
                  )}
                </div>
              ) : null}
              <div className="flex gap-3">
                <input
                  type="text"
                  value={otpCode}
                  onChange={(e) => {
                    setOtpCode(e.target.value);
                    // Treat the user typing as authoritative — stop
                    // overwriting with the delivered code from polling.
                    otpCodeRef.current = "__USER_TYPING__";
                  }}
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
            </>
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