-- Webhooks can arrive out of order: a booking.cancelled event may reach us
-- before its booking.created event. We record the cancellation as a
-- "placeholder" booking row that has no details yet, so a late booking.created
-- cannot resurrect a booking that was already cancelled.
ALTER TABLE bookings
    ALTER COLUMN customer_email DROP NOT NULL,
    ALTER COLUMN customer_name  DROP NOT NULL,
    ALTER COLUMN starts_at      DROP NOT NULL;

-- Only cancelled bookings may lack details.
ALTER TABLE bookings ADD CONSTRAINT bookings_details_present CHECK (
    status = 'cancelled'
    OR (customer_email IS NOT NULL AND customer_name IS NOT NULL AND starts_at IS NOT NULL)
);
