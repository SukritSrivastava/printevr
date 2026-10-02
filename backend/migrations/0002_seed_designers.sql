-- The first two designers, in rotation order: Namit gets the first job.
INSERT INTO designers (name, active, rotation_order) VALUES
    ('Namit', TRUE, 1),
    ('Ajendra', TRUE, 2)
ON CONFLICT (name) DO NOTHING;
