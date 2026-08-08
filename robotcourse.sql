-- ============================================================
-- AARI Educational Suite - Robotics Course Schema (Canvas-style)
-- Three in-person courses: Applied Mathematics (16-week math track),
-- Coding Fundamentals (14-week programming track), and Building Robots - weekly units
-- with 3 lecture days each; per-day Google slides, enrollment, and daily exit tickets.
-- Notes:
-- * Password columns store bcrypt hashes (strings), NEVER plaintext.
-- * Exit tickets are an ungraded retention signal, not homework:
-- `assignment` on Day describes what the exit ticket is (teacher-authored, student-visible);
-- students submit an optional attachment (`miniokey`) only - no written response.
-- * Parent tables created before children so FKs resolve.
-- * Safe to re-run in MySQL Workbench: drops existing tables first.
-- * Dummy seed data included below for local dev.
-- Default login password for all seed users: 123123 (override via TEST_PASSWORD in .env).
-- ============================================================

CREATE DATABASE IF NOT EXISTS `robcourse` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE `robcourse`;
SET NAMES utf8mb4;

-- Drop children before parents (FK order)
DROP TABLE IF EXISTS `exitTicket`;
DROP TABLE IF EXISTS `announcement`;
DROP TABLE IF EXISTS `class`;
DROP TABLE IF EXISTS `Day`;
DROP TABLE IF EXISTS `Week`;
DROP TABLE IF EXISTS `teacher`;
DROP TABLE IF EXISTS `students`;
DROP TABLE IF EXISTS `Course`;

-- ============================================================
-- Tables
-- ============================================================

CREATE TABLE `Course`(
 `courseid` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 `title` VARCHAR(255) NOT NULL,
 `syllabus` TEXT NOT NULL
);

CREATE TABLE `students`(
 `studentid` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 `fname` VARCHAR(255) NOT NULL,
 `lname` VARCHAR(255) NOT NULL,
 `email` VARCHAR(255) NOT NULL,
 `password` VARCHAR(255) NOT NULL
);
ALTER TABLE `students` ADD UNIQUE `students_email_unique`(`email`);

CREATE TABLE `teacher`(
 `teacherid` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 `fname` VARCHAR(255) NOT NULL,
 `lname` VARCHAR(255) NOT NULL,
 `email` VARCHAR(255) NOT NULL,
 `password` VARCHAR(255) NOT NULL,
 `courseid` BIGINT UNSIGNED NOT NULL
);
ALTER TABLE `teacher` ADD UNIQUE `teacher_email_unique`(`email`);

CREATE TABLE `Week`(
 `weekid` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 `courseid` BIGINT UNSIGNED NOT NULL,
 `title` VARCHAR(255) NOT NULL,
 `num` TINYINT UNSIGNED NOT NULL
);

-- Day owns the slide deck and exit-ticket prompt for each lecture (one per day)
CREATE TABLE `Day`(
 `dayid` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 `weekid` BIGINT UNSIGNED NOT NULL,
 `num` TINYINT UNSIGNED NOT NULL,
 `title` VARCHAR(255) NOT NULL,
 `description` VARCHAR(255) NOT NULL,
 `assignment` TEXT NOT NULL, -- teacher-set description of what the exit ticket is
 `slidelink` VARCHAR(255) NOT NULL
);

CREATE TABLE `class`(
 `classid` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 `studentid` BIGINT UNSIGNED NOT NULL,
 `courseid` BIGINT UNSIGNED NOT NULL
);

-- Tracked per day; slidelink removed (now lives on Day, not duplicated per ticket)
CREATE TABLE `exitTicket`(
 `ticketid` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 `dayid` BIGINT UNSIGNED NOT NULL,
 `classid` BIGINT UNSIGNED NOT NULL,
 `studentid` BIGINT UNSIGNED NOT NULL,
 `miniokey` VARCHAR(255) NULL,
 `response` TEXT NULL -- legacy; students no longer write reflections
);

CREATE TABLE `announcement`(
 `announceid` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 `courseid` BIGINT UNSIGNED NOT NULL,
 `content` TEXT NOT NULL,
 `created_at` DATETIME NOT NULL
);

ALTER TABLE `teacher` ADD CONSTRAINT `teacher_courseid_foreign` FOREIGN KEY(`courseid`) REFERENCES `Course`(`courseid`);
ALTER TABLE `Week` ADD CONSTRAINT `week_courseid_foreign` FOREIGN KEY(`courseid`) REFERENCES `Course`(`courseid`);
ALTER TABLE `Day` ADD CONSTRAINT `day_weekid_foreign` FOREIGN KEY(`weekid`) REFERENCES `Week`(`weekid`);
ALTER TABLE `class` ADD CONSTRAINT `class_studentid_foreign` FOREIGN KEY(`studentid`) REFERENCES `students`(`studentid`);
ALTER TABLE `class` ADD CONSTRAINT `class_courseid_foreign` FOREIGN KEY(`courseid`) REFERENCES `Course`(`courseid`);
ALTER TABLE `exitTicket` ADD CONSTRAINT `exitticket_dayid_foreign` FOREIGN KEY(`dayid`) REFERENCES `Day`(`dayid`);
ALTER TABLE `exitTicket` ADD CONSTRAINT `exitticket_classid_foreign` FOREIGN KEY(`classid`) REFERENCES `class`(`classid`);
ALTER TABLE `exitTicket` ADD CONSTRAINT `exitticket_studentid_foreign` FOREIGN KEY(`studentid`) REFERENCES `students`(`studentid`);
ALTER TABLE `announcement` ADD CONSTRAINT `announcement_courseid_foreign` FOREIGN KEY(`courseid`) REFERENCES `Course`(`courseid`);

-- ============================================================
-- Seed data (local development)
-- Bcrypt hash of default dev password "123123" - override with make_test_login.py + TEST_PASSWORD in .env
-- ============================================================

SET @pw = '123123';

INSERT INTO `Course` (`courseid`, `title`, `syllabus`) VALUES
(1, 'Applied Mathematics',
 'A 16-week math track for the AARI robotics program (3 days per week).

Phase 1 - Foundations (Weeks 1-5): Algebra (FOIL, quadratics, Pascal''s Triangle); Calculus (limits, derivatives, integrals); Geometry (polygons, circles, Pythagorean theorem); Vectors (magnitude, components, vector arithmetic); Trigonometry (unit circle, inverse trig, trig derivatives/integrals).

Phase 2 - Mechanics (Weeks 6-9): Translational motion, kinematic graphs, Newton''s second law; kinematic equations and calculus connections; rotational motion and wheel-to-robot velocity; friction, energy, momentum.

Phase 3 - Discrete Math (Weeks 10-12): Truth tables and digital circuits; Boolean algebra and De Morgan''s Laws; direct proof, contradiction, and contraposition.

Phase 4 - Linear Algebra (Weeks 13-16): Matrix operations and RREF; dot/cross/outer products and neural-network structure; forward pass and activations; loss, backpropagation, and end-to-end synthesis.

Each lecture day has its own slide deck and exit ticket - ungraded reflections on what clicked that day.'),
(2, 'Coding Fundamentals',
 'A 14-week in-person programming track for the AARI robotics program (10-11:50am: one hour lecture, one hour code-along).

Phase 1 - Basic Programming (Weeks 1-3, Ahmed Kiel-Kamil): Terminal setup and the four pillars of CS; variables, I/O, control flow; loops, arrays, functions, recursion, binary and hex; libraries (cmath, rand, iomanip); C++ classes and the four OOP pillars. Deliverable: Tic-Tac-Toe or Blackjack with at least one class.

Phase 2 - Low Level Computing (Weeks 4-14, JC Thomas III): Pointers, linked lists, dynamic arrays, and vectors; serial protocols and bitwise networking; computer architecture and compilation; feedback control and omni drive; graphs (DFS, BFS, Dijkstra, A*); finite state machines and bug navigation; odometry and coordinate frames; NumPy matrix operations; neural networks from perceptrons through scikit-learn comparison.

Each lecture day has its own slide deck and exit ticket - capture what clicked after every session.'),
(3, 'Building Robots',
 'Turn ideas into moving machines. Six build weeks with three lab days each - design a chassis, wire motors, assemble drive trains, and power your build safely. Each day adds a hands-on skill toward demo-day. Safety and teamwork come first - nobody builds alone.');

INSERT INTO `students` (`studentid`, `fname`, `lname`, `email`, `password`) VALUES
(1, 'Jaylen', 'Carter', 'jaylen.carter@student.aari.org', @pw),
(2, 'Destiny', 'Mitchell', 'destiny.mitchell@student.aari.org', @pw),
(3, 'Amir', 'Johnson', 'amir.johnson@student.aari.org', @pw),
(4, 'Kayla', 'Robinson', 'kayla.robinson@student.aari.org', @pw),
(5, 'DeShawn', 'Harris', 'deshawn.harris@student.aari.org', @pw),
(6, 'Taylor', 'Nguyen', 'taylor.nguyen@student.aari.org', @pw),
(7, 'Isaiah', 'Brooks', 'isaiah.brooks@student.aari.org', @pw),
(8, 'Mia', 'Williams', 'mia.williams@student.aari.org', @pw),
(9, 'Chris', 'Okafor', 'chris.okafor@student.aari.org', @pw),
(10, 'Zaria', 'Davis', 'zaria.davis@student.aari.org', @pw),
(11, 'Jordan', 'Lee', 'jordan.lee@student.aari.org', @pw),
(12, 'Nia', 'Patterson', 'nia.patterson@student.aari.org', @pw),
(13, 'Elijah', 'Gray', 'elijah.gray@student.aari.org', @pw),
(14, 'Amara', 'Singh', 'amara.singh@student.aari.org', @pw),
(15, 'Caleb', 'Washington','caleb.washington@student.aari.org', @pw);

INSERT INTO `teacher` (`teacherid`, `fname`, `lname`, `email`, `password`, `courseid`) VALUES
(1, 'Jasmine', 'Williams', 'jasmine.williams@aari.org', @pw, 1),
(2, 'Ahmed', 'Kiel-Kamil', 'ahmed.kielkamil@gmail.com', @pw, 2),
(3, 'Winston', 'Doss', 'doss.winston@gmail.com', @pw, 3);

INSERT INTO `class` (`classid`, `studentid`, `courseid`) VALUES
(1, 1, 1), (2, 1, 2), (3, 1, 3),
(4, 2, 1), (5, 2, 2),
(6, 3, 1), (7, 3, 2), (8, 3, 3),
(9, 4, 1), (10, 4, 3),
(11, 5, 1), (12, 5, 2), (13, 5, 3),
(14, 6, 1), (15, 6, 2),
(16, 7, 1), (17, 7, 3),
(18, 8, 2), (19, 8, 3),
(20, 9, 2), (21, 9, 3),
(22, 10, 1), (23, 10, 2),
(24, 11, 1), (25, 11, 3),
(26, 12, 2), (27, 12, 3),
(28, 13, 1), (29, 13, 2),
(30, 14, 1), (31, 14, 3),
(32, 15, 2), (33, 15, 3);

INSERT INTO `announcement` (`announceid`, `courseid`, `content`, `created_at`) VALUES
(1, 1,
 'Welcome to Applied Mathematics! We meet three days per week - Day 1 is FOIL & polynomial expansion. Each day has its own slides and exit ticket under Modules.',
 '2026-01-06 08:30:00'),
(2, 1,
 'Phase 2 - Mechanics starts Week 6. Review derivatives (Week 2) and vectors (Week 4) before Day 1 on translational motion.',
 '2026-02-10 09:00:00'),
(3, 1,
 'Phase 3 - Discrete Math begins Week 10. Day 1 covers logical expressions; if you are in Coding Fundamentals, this connects to bitwise ops later.',
 '2026-03-10 08:45:00'),
(4, 1,
 'Phase 4 - Linear Algebra starts Week 13. Week 14 Day 3 bridges matrices to neural networks; Week 16 Day 3 is the end-to-end synthesis session.',
 '2026-04-07 10:00:00'),
(5, 2,
 'Welcome to Coding Fundamentals! Phase 1 Day 1 with Ahmed - terminal setup and the four pillars of CS. Submit your exit ticket after each session.',
 '2026-01-06 09:15:00'),
(6, 2,
 'Week 3 Day 3 capstone: Tic-Tac-Toe or Blackjack using at least one C++ class. Separate functions for win/loss/draw logic.',
 '2026-01-20 16:30:00'),
(7, 2,
 'Phase 2 begins Week 4 Day 1 with JC Thomas III - pointers and memory. Week 7 Day 3: Control Loop Simulator deliverable.',
 '2026-01-27 10:00:00'),
(8, 2,
 'Week 8 Day 3 deliverable: Omni Drive Command Calculator. Week 10 Day 3: text-based navigation simulator with 3+ FSM states.',
 '2026-03-03 09:15:00'),
(9, 2,
 'Week 14 Day 3 final deliverable: Neural Network Accuracy Comparison across kNN, logistic regression, and MLP.',
 '2026-04-28 11:00:00'),
(10, 3,
 'Building Robots kicks off today! Day 1 slides cover what counts as a robot. Wear closed-toe shoes and safety goggles in the build zone.',
 '2026-01-06 10:00:00'),
(11, 3,
 'Week 2 Day 3 cross-bracing lab - teams assigned on the board by the door. Grab kits from your shelf label.',
 '2026-01-13 09:30:00'),
(12, 3,
 'Week 6 Day 3 is Demo Day. One reliable behavior beats five shaky ones - use Day 1 checklist slides to prep.',
 '2026-01-27 11:00:00');

INSERT INTO `Week` (`weekid`, `courseid`, `title`, `num`) VALUES
(1, 1, 'Algebra', 1),
(2, 1, 'Calculus', 2),
(3, 1, 'Geometry', 3),
(4, 1, 'Vectors', 4),
(5, 1, 'Trigonometry', 5),
(6, 1, 'Translational Motion I', 6),
(7, 1, 'Translational Motion II to Rotational Motion Intro', 7),
(8, 1, 'Rotational Motion', 8),
(9, 1, 'Friction & Energy', 9),
(10, 1, 'Truth Tables & Circuits', 10),
(11, 1, 'Circuits to Boolean Algebra', 11),
(12, 1, 'Proofs', 12),
(13, 1, 'Linear Algebra Fundamentals', 13),
(14, 1, 'Linear Algebra to Neural Networks', 14),
(15, 1, 'Neural Networks I', 15),
(16, 1, 'Neural Networks II', 16),
(17, 2, 'Programming: Data vs Logic', 1),
(18, 2, 'Abstraction', 2),
(19, 2, 'Abstraction 2', 3),
(20, 2, 'Pointers', 4),
(21, 2, 'Networking', 5),
(22, 2, 'Computer Architecture', 6),
(23, 2, 'Feedback Control', 7),
(24, 2, 'Omni Drive Geometry & Wall Following', 8),
(25, 2, 'Graphs', 9),
(26, 2, 'State Machines & Bug Navigation', 10),
(27, 2, 'Odometry & Coordinate Frames', 11),
(28, 2, 'Matrix Operations with Python', 12),
(29, 2, 'Neural Networks I: Foundations', 13),
(30, 2, 'Neural Networks II: Training & Comparison', 14),
(31, 3, 'What Is a Robot?', 1),
(32, 3, 'Structure & Chassis Design', 2),
(33, 3, 'Motors & Movement', 3),
(34, 3, 'Wheels, Gears & Drive Trains', 4),
(35, 3, 'Wiring & Power Basics', 5),
(36, 3, 'Demo Day Build-Off', 6);

INSERT INTO `Day` (`dayid`, `weekid`, `num`, `title`, `description`, `assignment`, `slidelink`) VALUES
(1, 1, 1, 'FOIL & Polynomial Expansion', 'Expand and factor polynomials using FOIL.', 'Expand (x+3)(x+5) and (2x-1)(x+4) by hand. In your exit ticket, show both products and note where you had to watch signs.', 'https://slides.aari.org/math/w1d1'),
(2, 1, 2, 'Quadratic Formula', 'Solve quadratics with the quadratic formula and discriminant.', 'Solve x² - 5x + 6 = 0 using the quadratic formula. Submit the discriminant value and both roots; say whether you could have factored instead.', 'https://slides.aari.org/math/w1d2'),
(3, 1, 3, 'Pascal''s Triangle & Binomial Expansion', 'Use Pascal''s Triangle for binomial expansion.', 'Write the binomial expansion of (a+b)³ using Pascal''s Triangle. In your exit ticket, explain what the row of the triangle represents.', 'https://slides.aari.org/math/w1d3'),
(4, 2, 1, 'Limits', 'Define limits as approaching a value.', 'Evaluate lim(x to 2) (x²-4)/(x-2) without a calculator. Explain in your exit ticket what "approaching" means vs "arriving."', 'https://slides.aari.org/math/w2d1'),
(5, 2, 2, 'Derivatives', 'Power, chain, and product rules; instantaneous rate of change.', 'Differentiate f(x)=3x³-2x and g(x)=(2x+1)⁴. Name which rule you used for each in your exit ticket.', 'https://slides.aari.org/math/w2d2'),
(6, 2, 3, 'Integrals & Inverse Operations', 'Basic integration techniques; derivatives and integrals as inverses.', 'Find ∫(6x²)dx and verify by differentiating your answer. In your exit ticket, explain why integration undoes differentiation.', 'https://slides.aari.org/math/w2d3'),
(7, 3, 1, 'Perimeter & Area of Polygons', 'Compute perimeter and area for robot footprint layouts.', 'Sketch a rectangular robot footprint with length 12 in and width 8 in. Submit perimeter, area, and one real build where area matters.', 'https://slides.aari.org/math/w3d1'),
(8, 3, 2, 'Circles & Physical Space', 'Circle area/circumference; estimating occupied space.', 'A wheel has radius 3 in. Compute circumference and area. In your exit ticket, estimate how much floor space a 360° spin covers.', 'https://slides.aari.org/math/w3d2'),
(9, 3, 3, 'Angles & Pythagorean Theorem', 'Degrees vs radians; right-triangle distance on the field.', 'Convert 90° and 45° to radians. Use the Pythagorean theorem to find the diagonal of a 6×8 ft field; show work in your exit ticket.', 'https://slides.aari.org/math/w3d3'),
(10, 4, 1, 'Defining Vectors', 'Magnitude, direction, and graphical representation.', 'Draw a vector from origin to (3,4). Compute its magnitude. In your exit ticket, describe direction in plain language.', 'https://slides.aari.org/math/w4d1'),
(11, 4, 2, 'Vector Components', 'Decompose and reconstruct vectors in x/y components.', 'Decompose a 10-unit vector at 30° into x and y components. Show trig setup and rounded values in your exit ticket.', 'https://slides.aari.org/math/w4d2'),
(12, 4, 3, 'Vector Arithmetic', 'Add, subtract, and scale vectors; displacement and force.', 'Add vectors (2,1) + (-1,3) and interpret the result as a displacement. Explain what subtraction would mean physically.', 'https://slides.aari.org/math/w4d3'),
(13, 5, 1, 'Unit Circle & Basic Trig', 'Evaluate sin, cos, tan at standard angles.', 'Without a calculator, give sin(π/6), cos(π/4), and tan(π/3). Note which values you memorized vs derived.', 'https://slides.aari.org/math/w5d1'),
(14, 5, 2, 'Reciprocal & Inverse Trig', 'Sec/cot/csc and inverse trig functions.', 'Find an angle θ in [0,π/2] where sin(θ)=0.6 using inverse sine. Show calculator steps or triangle sketch.', 'https://slides.aari.org/math/w5d2'),
(15, 5, 3, 'Trig Derivatives & Integrals', 'Differentiate and integrate trig with chain rule and substitution.', 'Differentiate f(x)=sin(3x). In your exit ticket, identify the inner function and how the chain rule applies.', 'https://slides.aari.org/math/w5d3'),
(16, 6, 1, 'Position, Velocity & Acceleration', 'Instantaneous vs average quantities in straight-line motion.', 'A robot moves from x=0 to x=12 m in 4 s. Compute average velocity. Compare to a case where it speeds up mid-run.', 'https://slides.aari.org/math/w6d1'),
(17, 6, 2, 'Motion Graphs', 'Slope and area on position-time and velocity-time graphs.', 'Given a straight-line segment on a x-t graph, explain how slope gives velocity and how area under v-t gives displacement.', 'https://slides.aari.org/math/w6d2'),
(18, 6, 3, 'Newton''s Second Law', 'Apply F = ma to translational robot motion.', 'A 2 kg robot needs a=3 m/s². Find required force. Relate one motor limitation you have seen in build class.', 'https://slides.aari.org/math/w6d3'),
(19, 7, 1, 'Kinematic Equations', 'Constant-acceleration kinematic equations.', 'A robot starts at rest and accelerates at 2 m/s² for 3 s. Find final velocity and displacement using kinematic equations.', 'https://slides.aari.org/math/w7d1'),
(20, 7, 2, 'Calculus & Motion', 'Use derivatives/integrals between position, velocity, displacement.', 'If v(t)=4t, find x(t) assuming x(0)=0. In your exit ticket, explain which operation connects v and x.', 'https://slides.aari.org/math/w7d2'),
(21, 7, 3, 'Angular Motion Intro', 'Angular position, velocity, acceleration as rotational analogs.', 'Define angular velocity in your own words and give one robot part that rotates instead of translating.', 'https://slides.aari.org/math/w7d3'),
(22, 8, 1, 'Torque & Rotational Dynamics', 'Newton''s second law for rotation: τ = Iα.', 'Explain τ=Iα in words. Give one example of torque on a robot wheel assembly from today''s demo.', 'https://slides.aari.org/math/w8d1'),
(23, 8, 2, 'Rotational Kinematics', 'Equations for constant angular acceleration.', 'A wheel accelerates from 0 to 10 rad/s in 2 s. Find angular acceleration. Show the equation you used.', 'https://slides.aari.org/math/w8d2'),
(24, 8, 3, 'Linear ↔ Angular & Wheel Velocity', 'Convert via radius; wheel speed to robot translational velocity.', 'A 5 cm radius wheel spins at 20 rad/s. Compute linear speed at the rim. Connect this to how your bot moves.', 'https://slides.aari.org/math/w8d3'),
(25, 9, 1, 'Variable Acceleration & Drag', 'When constant-acceleration breaks; integration for drag.', 'Describe a motion scenario where acceleration is not constant (e.g. drag). Why can''t you use the standard kinematic equations?', 'https://slides.aari.org/math/w9d1'),
(26, 9, 2, 'Kinetic Energy & Work-Energy', 'KE = ½mv² and the work-energy theorem.', 'Compute KE for a 1.5 kg robot moving at 2 m/s. In your exit ticket, explain work-energy in one sentence.', 'https://slides.aari.org/math/w9d2'),
(27, 9, 3, 'Momentum & Collisions', 'Momentum and conservation in collisions.', 'Two carts collide in the demo - describe what quantity was conserved and what your exit ticket observation was.', 'https://slides.aari.org/math/w9d3'),
(28, 10, 1, 'Logical Expressions', 'Translate language into AND/OR/NOT/implication.', 'Write a logic expression for "motor runs if button pressed AND battery ok." Build its truth table in your exit ticket.', 'https://slides.aari.org/math/w10d1'),
(29, 10, 2, 'Truth Tables & Equivalence', 'Build truth tables; check logical equivalence.', 'Show truth tables for A∧B and ¬(¬A∨¬B). State whether they are equivalent and cite De Morgan if yes.', 'https://slides.aari.org/math/w10d2'),
(30, 10, 3, 'Digital Circuits', 'Trace gates; series and parallel current.', 'Trace the output of a 2-input AND followed by NOT. Sketch or describe the gate path in your exit ticket.', 'https://slides.aari.org/math/w10d3'),
(31, 11, 1, 'Finite State Machines', 'Model multi-state systems as FSMs.', 'Sketch a 3-state FSM for a door (locked/unlocked/open). List states and one transition condition each.', 'https://slides.aari.org/math/w11d1'),
(32, 11, 2, 'Boolean Simplification', 'Simplify expressions with tautology equivalences.', 'Simplify A·B + A·¬B. Show steps and the final expression in your exit ticket.', 'https://slides.aari.org/math/w11d2'),
(33, 11, 3, 'De Morgan''s Laws', 'Apply De Morgan''s Laws to simplify circuits.', 'Apply De Morgan to ¬(A∨B) and to ¬(A∧B). Explain in words what each transformation does.', 'https://slides.aari.org/math/w11d3'),
(34, 12, 1, 'Direct Proof', 'Construct direct proofs step by step.', 'Write a direct proof that the sum of two even integers is even. Number each logical step.', 'https://slides.aari.org/math/w12d1'),
(35, 12, 2, 'Proof by Contradiction', 'Assume the negation and derive a contradiction.', 'Outline a proof by contradiction that √2 is irrational - state the assumption and where it breaks.', 'https://slides.aari.org/math/w12d2'),
(36, 12, 3, 'Proof by Contraposition', 'Prove via the contrapositive.', 'For "if n² is even then n is even," write the contrapositive and explain why it is equivalent.', 'https://slides.aari.org/math/w12d3'),
(37, 13, 1, 'Matrix Operations', 'Define matrices; add, subtract, and scale.', 'Add [[1,2],[3,4]] + [[5,0],[1,2]] and compute 2A for A=[[1,1],[0,2]]. Show all work.', 'https://slides.aari.org/math/w13d1'),
(38, 13, 2, 'RREF & Linear Systems', 'Row-reduce to RREF; solve systems of equations.', 'Row-reduce a 2×3 augmented matrix from class to RREF. State the solution or why there is none.', 'https://slides.aari.org/math/w13d2'),
(39, 13, 3, 'Dot Product', 'Compute dot products and interpret geometrically.', 'Compute (1,2)·(3,4) and explain whether the vectors are roughly aligned or opposing.', 'https://slides.aari.org/math/w13d3'),
(40, 14, 1, 'Cross Product', '3D cross product and perpendicularity.', 'Compute (1,0,0)×(0,1,0). Describe the direction of the result and what perpendicularity means.', 'https://slides.aari.org/math/w14d1'),
(41, 14, 2, 'Outer Product', 'Encode relationships between component pairs.', 'Form the outer product of vectors [1,2] and [3,4]. Describe the shape of the result matrix.', 'https://slides.aari.org/math/w14d2'),
(42, 14, 3, 'NN Structure Bridge', 'Weight matrices, layers, and biases in neural networks.', 'Draw a 2-layer network with 2 inputs and 1 output. Label where weights and biases live.', 'https://slides.aari.org/math/w14d3'),
(43, 15, 1, 'Learning Paradigms', 'Supervised, unsupervised, and reinforcement learning.', 'Give one robotics example each for supervised, unsupervised, and reinforcement learning.', 'https://slides.aari.org/math/w15d1'),
(44, 15, 2, 'Forward Pass', 'Manual computation through a small network.', 'Run a forward pass for the tiny network on the board with inputs [1,0]. Show each layer''s values.', 'https://slides.aari.org/math/w15d2'),
(45, 15, 3, 'Activation Functions', 'ReLU, sigmoid, and why nonlinearity is required.', 'Apply ReLU to [-2,0,3]. Explain in your exit ticket why a network of only linear layers collapses.', 'https://slides.aari.org/math/w15d3'),
(46, 16, 1, 'Loss Functions', 'Measure gap between predicted and actual output.', 'For predicted 0.7 vs actual 1.0, compute simple squared error. Interpret what improving the model means.', 'https://slides.aari.org/math/w16d1'),
(47, 16, 2, 'Backpropagation & Gradient Descent', 'Update weights via backprop and gradient descent.', 'In plain language, explain what gradient descent tries to do to the loss.', 'https://slides.aari.org/math/w16d2'),
(48, 16, 3, 'End-to-End Synthesis', 'Trace input: matrices to forward pass to loss to weight update.', 'Trace one input through the full pipeline from Week 13-15. Name the step that still feels fuzzy.', 'https://slides.aari.org/math/w16d3'),
(49, 17, 1, 'Computer Science & Terminal Setup', 'Define computer science; four pillars (networking, programming, hardware, software); set up the terminal.', 'Open a terminal, run pwd, ls, and cd into one folder. Name the four CS pillars and one command you used in your exit ticket.', 'https://docs.google.com/presentation/d/1MteBM-1kGGTlRe7K9U-qyIYsaSDjg2pSoQh_mNcYCfQ/edit?usp=sharing'),
(50, 17, 2, 'Variables, I/O & Arithmetic', 'Input, output, variables, and arithmetic operators in C++.', 'Write a short program that reads two integers and prints their sum. Paste code or describe it; note one bug you fixed.', 'https://docs.google.com/presentation/d/18k6SfHWcj4ZPqOOy8ZsAEm6IWEbP0qhNOJjDE5KFd2Y/edit?usp=sharing'),
(51, 17, 3, 'Control Flow & Logic', 'Conditionals, control flow, and logical operators.', 'Write an if/else that classifies a sensor reading as HIGH or LOW. Submit pseudocode or C++ and explain your condition.', 'https://docs.google.com/presentation/d/1Jl3HA0xudg_Ek9Oqm3own6F1dE8yGvVtzTIXAynVFDM/edit?usp=sharing'),
(52, 18, 1, 'Loops & Arrays', 'for and while loops; arrays and iteration.', 'Write a loop that prints numbers 1-10 and stores them in an array. Say whether you used for or while and why.', 'https://docs.google.com/presentation/d/1K4Y__scey_iHj5_8XzY_5_t1VoVb4xPCZeNtqD52sN4/edit?usp=sharing'),
(53, 18, 2, 'Functions I', 'Define and call C++ functions with typed parameters and return values; reduce repetition.', 'Write a function double(int x) that returns 2x. Call it from main. Explain one way functions make code easier to reason about.', 'https://slides.aari.org/coding/w2d2'),
(54, 18, 3, 'Functions II: Recursion & Number Bases', 'Recursion; binary, hex, and decimal conversion.', 'Convert decimal 13 to binary and hex by hand. Write or describe a recursive function; state its base case.', 'https://slides.aari.org/coding/w2d3'),
(55, 19, 1, 'Libraries: cmath, rand & iomanip', 'Libraries as abstraction; cmath and rand for Blackjack; iomanip for tic-tac-toe boards.', 'Use rand() to draw a card value 1-13 OR format a board row with iomanip. Explain one library function you used today.', 'https://slides.aari.org/coding/w3d1'),
(56, 19, 2, 'Classes I: Encapsulation', 'Define a C++ class with members, constructors, accessors, and mutators.', 'Define a class with at least one field, constructor, and one accessor. Paste skeleton or describe encapsulation in your own words.', 'https://slides.aari.org/coding/w3d2'),
(57, 19, 3, 'Classes II: OOP Pillars & Capstone', 'Function-heavy vs data-heavy classes; four OOP pillars; Phase 1 capstone.', 'Continue Tic-Tac-Toe or Blackjack. Submit what you finished today and one class or function you added for win/loss/draw logic.', 'https://slides.aari.org/coding/w3d3'),
(58, 20, 1, 'RAM, ROM & Pointers', 'RAM vs ROM; pointers, allocation, and pass-by-reference.', 'Explain RAM vs ROM in your own words. Draw a pointer to an int; say what *p means in your exit ticket.', 'https://slides.aari.org/coding/w4d1'),
(59, 20, 2, 'Linked Lists', 'Build and use a linked list with pointer operations.', 'Describe insert or traverse steps for a linked list from class. Name one advantage over a fixed-size array.', 'https://slides.aari.org/coding/w4d2'),
(60, 20, 3, 'Dynamic Arrays & vector', 'Step-by-step dynamic array; introduce the vector library.', 'Allocate a small dynamic array with new[] or use vector.push_back. Describe one step that confused you.', 'https://slides.aari.org/coding/w4d3'),
(61, 21, 1, 'Serial Protocols & IP/MAC', 'UART, I2C, SPI; wired vs wireless robot links; IP and MAC addressing.', 'Name two serial protocols from today and one reason a robot uses IP addressing on its onboard computer.', 'https://slides.aari.org/coding/w5d1'),
(62, 21, 2, 'IP Addresses & Subnet Masks', 'Represent IP and subnet mask in binary; bitwise AND for network vs host.', 'Given a sample IP and mask, show the bitwise AND that yields the network portion. Show binary work in your exit ticket.', 'https://slides.aari.org/coding/w5d2'),
(63, 21, 3, 'Bitwise AND, OR & XOR', 'Subnet/broadcast addresses; register flags; XOR checksum for errors.', 'Compute 5 & 3 and 5 ^ 3 in binary. Give one robotics use for masking bits and one for XOR error detection.', 'https://slides.aari.org/coding/w5d3'),
(64, 22, 1, 'Architecture Overview', 'Memory hierarchy, CPU, motherboard, and PCI.', 'List three levels of the memory hierarchy from fastest to slowest. Tie one level to something your program uses.', 'https://slides.aari.org/coding/w6d1'),
(65, 22, 2, 'CPU & Registers', 'Fetch, decode, execute; role of registers.', 'Describe fetch-decode-execute in three short sentences as if explaining to a friend.', 'https://slides.aari.org/coding/w6d2'),
(66, 22, 3, 'The Compiler Pipeline', 'Trace C++ source through preprocess, compile, assemble, and link.', 'Order the four compiler stages. Say which stage handles #include and which produces the executable.', 'https://slides.aari.org/coding/w6d3'),
(67, 23, 1, 'Control Loop Foundations', 'Error as setpoint minus measured; sense-compute-actuate; continuous loop.', 'Define error for a robot holding 10 cm when measured is 7 cm. Sketch sense to compute to actuate.', 'https://slides.aari.org/coding/w7d1'),
(68, 23, 2, 'Bang-Bang Controller', 'Switch output based on the sign of error.', 'Describe bang-bang output when error is positive vs negative. Give one downside vs proportional control.', 'https://slides.aari.org/coding/w7d2'),
(69, 23, 3, 'Proportional Controller & Simulator', 'Proportional gain, live sensor loop; Control Loop Simulator deliverable.', 'Run the control simulator at two gains. Report which converged vs oscillated and how gain affected response.', 'https://slides.aari.org/coding/w7d3'),
(70, 24, 1, 'Omnidirectional Drive', 'Wheel velocities for combined translation and rotation on omni bases.', 'For forward motion only, describe which wheels spin on a 3-wheel omni base. Use a sketch or words.', 'https://slides.aari.org/coding/w8d1'),
(71, 24, 2, 'Polar to Cartesian (atan2)', 'Convert lidar distance/angle to x/y; why atan2 handles all quadrants.', 'Convert (distance=5, angle=45 deg) to x,y. Show setup; note why atan2 beats tan alone.', 'https://slides.aari.org/coding/w8d2'),
(72, 24, 3, 'Wall Following & Omni Calculator', 'Proportional wall follow; isolate sense/compute/actuate; Omni Drive Calculator deliverable.', 'Tune wall-following gain OR test omni calculator mode. Compare two gains or submit sample inputs/outputs.', 'https://slides.aari.org/coding/w8d3'),
(73, 25, 1, 'Graphs & DFS', 'Adjacency lists/matrices; depth-first search on a grid.', 'Sketch a small grid graph and list DFS visit order from a start cell. Why is DFS useful for exploration?', 'https://slides.aari.org/coding/w9d1'),
(74, 25, 2, 'BFS & Queues', 'Queue-based breadth-first search; shortest path in unweighted graphs.', 'Explain why BFS finds the shortest path in an unweighted grid. Trace BFS order on the board example.', 'https://slides.aari.org/coding/w9d2'),
(75, 25, 3, 'Dijkstra & A*', 'Weighted graphs; Dijkstra and A* with a heuristic for navigation.', 'Compare Dijkstra vs A* in one paragraph. When would A* typically expand fewer nodes?', 'https://slides.aari.org/coding/w9d3'),
(76, 26, 1, 'Finite State Machines', 'States, transitions, inputs, outputs; diagram before code.', 'Draw a state diagram for a simple robot behavior with at least 3 states. Label two transitions.', 'https://slides.aari.org/coding/w10d1'),
(77, 26, 2, 'FSM in C++', 'Implement FSM with enum and switch vs nested if-else.', 'Write enum + switch skeleton for your FSM. Explain one advantage over nested if-else.', 'https://slides.aari.org/coding/w10d2'),
(78, 26, 3, 'Bug Navigation & Grid Sim', '3+ state bug navigation FSM; Text-Based Navigation Simulator deliverable.', 'Name three states in bug navigation and one sensor-driven transition. List FSM states in your grid sim.', 'https://slides.aari.org/coding/w10d3'),
(79, 27, 1, 'Odometry & Dead Reckoning', 'Pose as (x, y, heading); update equations after each motion.', 'Define odometry in your own words. Write pose after one 1 m forward move from (0,0,0).', 'https://slides.aari.org/coding/w11d1'),
(80, 27, 2, 'Body-to-Global Transform', 'Transform a point from robot body frame to global map frame.', 'Explain body vs global frame. Why does heading error matter when transforming a local move?', 'https://slides.aari.org/coding/w11d2'),
(81, 27, 3, 'Drift & Odometry Tracker', 'Multi-step drift; wheel slip and encoder error; Odometry Tracker deliverable.', 'Run two paths in the odometry tracker. Report which drifted more and one likely cause.', 'https://slides.aari.org/coding/w11d3'),
(82, 28, 1, 'NumPy Arrays', 'Create, index, slice arrays; NumPy memory layout vs Python loops.', 'Create a 3x3 NumPy array and slice the second row. Explain why vectorized ops beat plain loops.', 'https://slides.aari.org/coding/w12d1'),
(83, 28, 2, 'Matrix Multiplication', 'Element-wise vs true matrix multiplication; compute by hand and in NumPy.', 'Multiply [[1,2],[0,1]] @ [[3],[4]] by hand. Contrast * vs @ in NumPy terms.', 'https://slides.aari.org/coding/w12d2'),
(84, 28, 3, 'Broadcasting & Image Transformer', 'Broadcasting rules; transpose; Python Image Transformer deliverable.', 'Apply one geometric transform to a sample image matrix. Name the matrix operation you used.', 'https://slides.aari.org/coding/w12d3'),
(85, 29, 1, 'Perceptron from Scratch', 'Define and implement a perceptron; what firing means.', 'Implement weights·inputs+bias threshold. Give inputs where your perceptron fires vs does not.', 'https://slides.aari.org/coding/w13d1'),
(86, 29, 2, 'ReLU & Nonlinearity', 'Implement ReLU; why nonlinear activations are necessary.', 'Code ReLU(x) in one line. Explain why deep linear nets collapse to a single linear model.', 'https://slides.aari.org/coding/w13d2'),
(87, 29, 3, 'Forward Pass & Collapse Proof', 'Manual forward pass through a small network; linear collapse proof.', 'Manual forward pass for a 2-input, 1-hidden, 1-output net. Restate the collapse proof in ≤3 sentences.', 'https://slides.aari.org/coding/w13d3'),
(88, 30, 1, 'Hyperparameters', 'Learning rate, layers, neurons; how each affects training.', 'Define learning rate in your own words. Predict what happens if learning rate is too high.', 'https://slides.aari.org/coding/w14d1'),
(89, 30, 2, 'Training with scikit-learn', 'MLPClassifier, confusion matrix on a held-out test set.', 'Train MLPClassifier on the sample dataset. Report one hyperparameter you changed and a confusion matrix takeaway.', 'https://slides.aari.org/coding/w14d2'),
(90, 30, 3, 'Model Comparison Deliverable', 'kNN vs logistic regression vs neural network; Accuracy Comparison deliverable.', 'Submit comparison table plus 2-3 sentences on when each model is likely to win.', 'https://slides.aari.org/coding/w14d3'),
(91, 31, 1, 'What Counts as a Robot?', 'Examples of robots; sensors, actuators, and computation.', 'List three things from today that count as robots and one that does not. Defend your choice in the exit ticket.', 'https://slides.aari.org/robotics/w1d1'),
(92, 31, 2, 'Robot Subsystems', 'How software, electronics, and mechanics fit together.', 'Draw or describe how software, electronics, and mechanics connect on your kit. Name one subsystem you will own.', 'https://slides.aari.org/robotics/w1d2'),
(93, 31, 3, 'From Idea to Build', 'Safety norms and teamwork before touching hardware.', 'Review club safety rules. In your exit ticket, state one safety rule and your team role for Week 2.', 'https://slides.aari.org/robotics/w1d3'),
(94, 32, 1, 'Materials & Constraints', 'Choose materials; plan a stable footprint.', 'Sketch chassis footprint and list materials. Explain one constraint (weight, stiffness, or size).', 'https://slides.aari.org/robotics/w2d1'),
(95, 32, 2, 'Chassis Layout', 'Sketch and assemble a rigid frame.', 'Photo or describe today''s chassis layout. Note one weak point you will reinforce tomorrow.', 'https://slides.aari.org/robotics/w2d2'),
(96, 32, 3, 'Cross-Bracing Lab', 'Strengthen the chassis; measure twice, cut once.', 'After cross-bracing, describe how stiffness changed. Optional: attach a photo in your exit ticket.', 'https://slides.aari.org/robotics/w2d3'),
(97, 33, 1, 'Motor Types & Wiring', 'Connect motors safely; identify terminals.', 'Document motor polarity labeling on your team bot. What happens if wires are reversed?', 'https://slides.aari.org/robotics/w3d1'),
(98, 33, 2, 'First Motion Test', 'Run motors; observe direction and speed.', 'Run first motion test. Report direction vs expected and one fix you made.', 'https://slides.aari.org/robotics/w3d2'),
(99, 33, 3, 'Controlled Movement', 'Basic speed and direction on the practice floor.', 'Describe how you controlled speed today. What still feels unpredictable?', 'https://slides.aari.org/robotics/w3d3'),
(100, 34, 1, 'Wheels & Traction', 'Pick wheels for surface and load.', 'Which wheels did your team pick and why? Relate traction to one math concept from Applied Mathematics.', 'https://slides.aari.org/robotics/w4d1'),
(101, 34, 2, 'Gear Ratios', 'Torque vs speed tradeoffs from Applied Mathematics.', 'Compute or estimate your gear ratio. Trade speed for torque - which did you prioritize?', 'https://slides.aari.org/robotics/w4d2'),
(102, 34, 3, 'Drive Train Assembly', 'Mount gears and wheels as a team.', 'List one assembly step that required teamwork. What would fail if done alone?', 'https://slides.aari.org/robotics/w4d3'),
(103, 35, 1, 'Battery Safety', 'Power distribution and club safety rules.', 'Explain when to connect/disconnect battery. Identify fuse or breaker location on your bot.', 'https://slides.aari.org/robotics/w5d1'),
(104, 35, 2, 'Signal vs Power Wiring', 'Route wires cleanly; avoid shorts.', 'Describe signal vs power wire routing on your bot. One thing you zip-tied or labeled.', 'https://slides.aari.org/robotics/w5d2'),
(105, 35, 3, 'Connection Troubleshooting', 'Debug loose or reversed connections.', 'Describe one wiring bug you found and how you isolated it.', 'https://slides.aari.org/robotics/w5d3'),
(106, 36, 1, 'Reliability Checklist', 'One solid behavior beats many flaky ones.', 'Pick one reliable behavior for demo day. Complete checklist items from slides in your exit ticket.', 'https://slides.aari.org/robotics/w6d1'),
(107, 36, 2, 'Demo Prep & Peer Review', 'Test runs and feedback before showcase.', 'Summarize peer feedback from test runs. One change you will make before demo.', 'https://slides.aari.org/robotics/w6d2'),
(108, 36, 3, 'Demo Day Presentations', 'Show the robot; reflect on the build season.', 'Reflect on the full build: what worked, what broke, what you would rebuild next time.', 'https://slides.aari.org/robotics/w6d3');

INSERT INTO `exitTicket` (`ticketid`, `dayid`, `classid`, `studentid`, `miniokey`) VALUES
(1, 1, 1, 1, NULL),
(2, 2, 4, 2, NULL),
(3, 3, 11, 5, NULL),
(4, 4, 6, 3, NULL),
(5, 7, 9, 4, NULL),
(6, 10, 16, 7, NULL),
(7, 16, 28, 13, NULL),
(8, 22, 30, 14, NULL),
(9, 25, 14, 6, NULL),
(10, 28, 24, 11, NULL),
(11, 34, 22, 10, NULL),
(12, 40, 1, 1, NULL),
(13, 42, 4, 2, NULL),
(14, 48, 28, 13, NULL),
(15, 49, 2, 1, NULL),
(16, 50, 5, 2, NULL),
(17, 52, 7, 3, NULL),
(18, 54, 12, 5, NULL),
(19, 56, 15, 6, NULL),
(20, 59, 18, 8, NULL),
(21, 62, 20, 9, NULL),
(22, 65, 29, 13, NULL),
(23, 66, 32, 15, NULL),
(24, 68, 2, 1, NULL),
(25, 73, 7, 3, NULL),
(26, 76, 12, 5, NULL),
(27, 79, 23, 10, NULL),
(28, 85, 26, 12, NULL),
(29, 88, 18, 8, NULL),
(30, 90, 29, 13, NULL),
(31, 91, 3, 1, NULL),
(32, 94, 8, 3, NULL),
(33, 95, 10, 4, 'exittickets/build_photo_12.jpg'),
(34, 98, 13, 5, NULL),
(35, 100, 17, 7, NULL),
(36, 102, 19, 8, 'exittickets/build_photo_19.jpg'),
(37, 108, 33, 15, NULL);