-- ============================================================
-- AARI Educational Suite & MySQL Schema
-- Data-center cohort courses (LinkedIn-Learning-style) + cohort chat
-- Notes:
--   * All password columns store bcrypt hashes (strings), NEVER plaintext.
--   * Chat membership and message senders are polymorphic (type + id)
--     so both students and admins can participate without merging
--     the two account tables. The (type,id) pair is validated in
--     application code, since a polymorphic FK can't be a DB constraint.
--   * Parent tables are created before children so FKs resolve.
--   * Safe to re-run in MySQL Workbench: drops existing tables first.
--   * Dummy seed data included below for local dev (placeholder passwords).
--     Use: python make_test_login.py --suite dc
-- ============================================================

CREATE DATABASE IF NOT EXISTS `bootcamp` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE `bootcamp`;
SET NAMES utf8mb4;

-- Drop children before parents (FK order)
DROP TABLE IF EXISTS `help_message`;
DROP TABLE IF EXISTS `messages`;
DROP TABLE IF EXISTS `channel_member`;
DROP TABLE IF EXISTS `assignment`;
DROP TABLE IF EXISTS `progress`;
DROP TABLE IF EXISTS `content`;
DROP TABLE IF EXISTS `channel`;
DROP TABLE IF EXISTS `student`;
DROP TABLE IF EXISTS `leader`;
DROP TABLE IF EXISTS `admin`;
DROP TABLE IF EXISTS `Week`;
DROP TABLE IF EXISTS `Course`;
DROP TABLE IF EXISTS `cohort`;

-- ============================================================
-- AARI Educational Suite & Data Center Course Schema
-- Asynchronous, LinkedIn-Learning-style cohort program with three
-- division-tracks (courses), weekly lessons, graded assignments,
-- cohort chat (general/division/direct), progress tracking, and roster bios.
-- Notes:
--   * Password columns store bcrypt hashes (strings), NEVER plaintext.
--   * Cohort leaders live in `leader` (cohort-scoped, no division track).
--   * Platform admins (`admin`) author course content across all tracks.
--   * channel_member / messages use polymorphic (type,id) so students
--     AND admins participate; the (type,id) pair is validated in app code
--     since a polymorphic FK cannot be a DB constraint.
--   * Parent tables created before children so FKs resolve.
-- ============================================================

CREATE TABLE `Course` (
    `courseid`    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `name`        VARCHAR(255) NOT NULL,
    `description` TEXT NOT NULL,
    `teacher`     VARCHAR(255) NOT NULL
);

CREATE TABLE `cohort` (
    `cohortid` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `region`   VARCHAR(255) NOT NULL,
    `name`     VARCHAR(255) NOT NULL
);

-- Platform course admins: author weeks/content across all division tracks (not cohort-scoped).
CREATE TABLE `admin` (
    `adminid`  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `fname`    VARCHAR(255) NOT NULL,
    `lname`    VARCHAR(255) NOT NULL,
    `email`    VARCHAR(255) NOT NULL,  -- also the Google Calendar guest for Help Desk bookings
    `password` VARCHAR(255) NULL,  -- bcrypt hash; NULL until first password login
    `signed_in_at` DATETIME NULL,  -- set on first password login or Microsoft Entra sign-in
    UNIQUE KEY `admin_email_unique` (`email`)
);

CREATE TABLE `leader` (
    `leaderid`  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `fname`     VARCHAR(255) NOT NULL,
    `lname`     VARCHAR(255) NOT NULL,
    `email`     VARCHAR(255) NOT NULL,
    `password`  VARCHAR(255) NULL,  -- bcrypt hash; NULL until first password login
    `cohortid`  BIGINT UNSIGNED NOT NULL,
    `bio`       TEXT NULL,
    UNIQUE KEY `leader_email_unique` (`email`),
    UNIQUE KEY `leader_cohort_unique` (`cohortid`),
    CONSTRAINT `leader_cohortid_fk` FOREIGN KEY (`cohortid`) REFERENCES `cohort` (`cohortid`)
);

CREATE TABLE `student` (
    `studentid` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `fname`     VARCHAR(255) NOT NULL,
    `lname`     VARCHAR(255) NOT NULL,
    `email`     VARCHAR(255) NOT NULL,
    `password`  VARCHAR(255) NULL,  -- bcrypt hash; NULL until first password login
    `courseid`  BIGINT UNSIGNED NOT NULL,  -- division assignment
    `college`   BOOLEAN NOT NULL DEFAULT FALSE,  -- college students: every week unlocked, no assignment gating
    `cohortid`  BIGINT UNSIGNED NULL,      -- required for non-college students; college students may have none
    `bio`       TEXT NULL,                 -- short roster bio
    `orchestration_branch` ENUM('software','hardware') NULL,  -- orchestration only: branch after week 4
    UNIQUE KEY `student_email_unique` (`email`),
    CONSTRAINT `student_courseid_fk` FOREIGN KEY (`courseid`) REFERENCES `Course` (`courseid`),
    CONSTRAINT `student_cohortid_fk` FOREIGN KEY (`cohortid`) REFERENCES `cohort` (`cohortid`)
);

CREATE TABLE `Week` (
    `weekid`      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `courseid`    BIGINT UNSIGNED NOT NULL,
    `subject`     VARCHAR(255) NOT NULL,
    `num`         TINYINT UNSIGNED NOT NULL,
    `description` TEXT NOT NULL,
    `branch`      ENUM('shared','software','hardware') NOT NULL DEFAULT 'shared',
    CONSTRAINT `week_courseid_fk` FOREIGN KEY (`courseid`) REFERENCES `Course` (`courseid`)
);

CREATE TABLE `content` (
    `videoid`      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `weekid`       BIGINT UNSIGNED NOT NULL,
    `day`          TINYINT UNSIGNED NOT NULL,  -- lecture day within the week (1–3)
    `title`        VARCHAR(255) NOT NULL,
    `miniokey`     VARCHAR(255) NULL,      -- MinIO object key for a lesson video
    `pdfkey`       VARCHAR(255) NULL,      -- MinIO object key for a PDF lesson document
    `instructionskey` VARCHAR(255) NULL,   -- MinIO object key for the assignment instructions PDF
    `script`       TEXT NULL,              -- instructor script (optional until authored)
    `instructions` TEXT NULL,              -- what students submit (deliverable instructions)
    `reflection`   TEXT NULL,              -- instructor reflection on the assignment
    CONSTRAINT `content_weekid_fk` FOREIGN KEY (`weekid`) REFERENCES `Week` (`weekid`)
);

-- Graded assignment submission, one per (student, content) attempt.
CREATE TABLE `assignment` (
    `assignmentid` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `videoid`      BIGINT UNSIGNED NOT NULL,
    `studentid`    BIGINT UNSIGNED NOT NULL,
    `miniokey`     VARCHAR(255) NOT NULL,  -- submitted file in MinIO
    `status`       ENUM('submitted','satisfactory','unsatisfactory') NOT NULL DEFAULT 'submitted',
    `feedback`     VARCHAR(255) NULL,       -- admin's written feedback; null until graded
    `submitted_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT `assignment_videoid_fk` FOREIGN KEY (`videoid`) REFERENCES `content` (`videoid`),
    CONSTRAINT `assignment_studentid_fk` FOREIGN KEY (`studentid`) REFERENCES `student` (`studentid`)
);

-- Lesson progress, one row per (student, content).
CREATE TABLE `progress` (
    `studentid`     BIGINT UNSIGNED NOT NULL,
    `videoid`       BIGINT UNSIGNED NOT NULL,
    `watched`       BOOLEAN NOT NULL DEFAULT FALSE,
    `last_position` INT UNSIGNED NOT NULL DEFAULT 0,  -- seconds into the video (resume point)
    `updated_at`    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`studentid`, `videoid`),
    CONSTRAINT `progress_studentid_fk` FOREIGN KEY (`studentid`) REFERENCES `student` (`studentid`),
    CONSTRAINT `progress_videoid_fk` FOREIGN KEY (`videoid`) REFERENCES `content` (`videoid`)
);

CREATE TABLE `channel` (
    `channelid` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `cohortid`  BIGINT UNSIGNED NOT NULL,
    `type`      ENUM('general','division','direct') NOT NULL,
    `name`      VARCHAR(255) NULL,  -- nullable: DMs have no name
    CONSTRAINT `channel_cohortid_fk` FOREIGN KEY (`cohortid`) REFERENCES `cohort` (`cohortid`)
);

CREATE TABLE `channel_member` (
    `channelid`   BIGINT UNSIGNED NOT NULL,
    `member_type` ENUM('student','leader','admin') NOT NULL,
    `member_id`   BIGINT UNSIGNED NOT NULL,  -- validated in app code per member_type
    PRIMARY KEY (`channelid`, `member_type`, `member_id`),
    CONSTRAINT `cm_channel_fk` FOREIGN KEY (`channelid`) REFERENCES `channel` (`channelid`)
);

CREATE TABLE `messages` (
    `messagesid`  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `channelid`   BIGINT UNSIGNED NOT NULL,
    `sender_type` ENUM('student','leader','admin') NOT NULL,
    `sender_id`   BIGINT UNSIGNED NOT NULL,  -- validated in app code per sender_type
    `content`     TEXT NOT NULL,
    `sendtime`    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX `messages_channelid_index` (`channelid`),
    CONSTRAINT `messages_channelid_fk` FOREIGN KEY (`channelid`) REFERENCES `channel` (`channelid`)
);

-- 1:1 Help Desk thread between a student and a platform admin (not cohort Messenger).
-- studentid/adminid identify the pair; sender_type is who wrote this row so admins can reply.
CREATE TABLE `help_message` (
    `help_messageid` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `studentid`      BIGINT UNSIGNED NOT NULL,
    `adminid`        BIGINT UNSIGNED NOT NULL,
    `sender_type`    ENUM('student','admin') NOT NULL,
    `content`        TEXT NOT NULL,
    `sendtime`       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX `help_message_thread_index` (`studentid`, `adminid`, `sendtime`),
    CONSTRAINT `help_message_studentid_fk` FOREIGN KEY (`studentid`) REFERENCES `student` (`studentid`),
    CONSTRAINT `help_message_adminid_fk` FOREIGN KEY (`adminid`) REFERENCES `admin` (`adminid`)
);


-- ============================================================
-- Seed data (local development)
-- Curriculum: Data Center Orchestration (8 weeks, branching),
-- Cloud Architect, Power Delivery (6 weeks × 3 sessions each)
-- Use: python make_test_login.py --suite dc --reset-all
-- ============================================================

SET @pw = '123123';

INSERT INTO `Course` (`courseid`, `name`, `description`, `teacher`) VALUES
(1, 'Data Center Orchestration', 'Eight-week branching track for the data center: four shared foundation weeks, then two software weeks (web development and full-stack monitoring) and two hardware weeks (facility architecture and security). From C++ and low-level computing through Proxmox, Express, MySQL, spine-leaf design, and incident response.', 'Ahmed Kiel-Kamil'),
(2, 'Cloud Architect', 'Six-week path from cloud fundamentals and Python through AI/RAG, Flask/MySQL, JavaScript front ends, Azure deployment, and a community cloud business proposal — building ordering platforms local businesses can actually use.', 'Ahmed Kiel-Kamil'),
(3, 'Power Delivery', 'Six-week track from Ohm''s law and electrical safety through data center architecture, thermodynamics and cooling, grid energy systems, Python, and a Flask energy monitoring dashboard capstone — the physical infrastructure foundation for the community cloud.', 'Ahmed Kiel-Kamil');

INSERT INTO `cohort` (`cohortid`, `region`, `name`) VALUES
(1, 'Atlanta', 'Cohort 1'),
(2, 'Atlanta', 'Cohort 2');

INSERT INTO `admin` (`adminid`, `fname`, `lname`, `email`, `password`) VALUES
(1, 'Charles', 'Butler', 'cb3student@gmail.com', @pw),
(2, 'Ahmed', 'Kiel-Kamil', 'ahmed.kielkamil@outlook.com', @pw),
(3, 'Ryan', 'Charles', 'cssryans@gmail.com', @pw),
(4, 'Gman', 'Roper', 'gmanroper@gmail.com', @pw),
(5, 'Nolan', 'Code', 'nolan@atlanta-robotics.org', @pw);

INSERT INTO `leader` (`leaderid`, `fname`, `lname`, `email`, `password`, `cohortid`, `bio`) VALUES
(1, 'Denise', 'Parker', 'denise.parker@aari.org', @pw, 1, 'Cohort 1 leader — cross-track support, grading, and cohort chat.'),
(2, 'Robert', 'Kim', 'robert.kim@aari.org', @pw, 2, 'Cohort 2 leader — cross-track support and grading.');

INSERT INTO `student` (`studentid`, `fname`, `lname`, `email`, `password`, `courseid`, `college`, `cohortid`, `bio`, `orchestration_branch`) VALUES
(1, 'Chemere', 'Redfern', 'clredfern11@gmail.com', @pw, 1, FALSE, 1, 'Orchestration software specialist - building the Splunk monitoring dashboard.', 'software'),
(2, 'Keisha', 'Williams', 'keisha.williams@aari.org', @pw, 1, FALSE, 1, 'Porting C++ Hangman to JavaScript this week.', 'software'),
(3, 'David', 'Nguyen', 'david.nguyen@aari.org', @pw, 2, FALSE, 1, 'Cloud Architect — building a tutoring-industry ordering platform with Customer, ServiceProvider, and Order classes.', NULL),
(4, 'Angela', 'Martinez', 'angela.martinez@aari.org', @pw, 2, FALSE, 1, 'Working on Flask + MySQL reviews table for my service-ordering app.', NULL),
(5, 'Terrence', 'Jackson', 'terrence.jackson@aari.org', @pw, 3, FALSE, 1, 'Power Delivery track — working through circuit analysis before sizing cohort rack loads.', NULL),
(6, 'Michelle', 'Chen', 'michelle.chen@aari.org', @pw, 3, FALSE, 1, 'Drafting spine-leaf and hot/cold aisle layouts for our Atlanta facility.', NULL),
(7, 'Brian', 'O''Connor', 'brian.oconnor@aari.org', @pw, 1, FALSE, 2, 'RAID lab in VirtualBox - orchestration track.', 'hardware'),
(8, 'Renee', 'Foster', 'renee.foster@aari.org', @pw, 1, FALSE, 2, 'Express dashboard connecting to /servers API.', 'software'),
(9, 'Carlos', 'Rivera', 'carlos.rivera@aari.org', @pw, 2, FALSE, 2, 'RAG chatbot for auto-repair industry on my community-cloud site.', NULL),
(10, 'Nicole', 'Adams', 'nicole.adams@aari.org', @pw, 2, FALSE, 2, 'Deploying the ordering platform to Azure Container Apps with Docker and MSAL auth.', NULL),
(11, 'Kevin', 'Patel', 'kevin.patel@aari.org', @pw, 3, FALSE, 2, 'Power Delivery — power redundancy analysis for cohort pod, N+1 calculations.', NULL),
(12, 'Jasmine', 'Wright', 'jasmine.wright@aari.org', @pw, 3, FALSE, 2, 'Building the Python/Flask energy dashboard — live PUE charts from simulated PDU sensors.', NULL),
-- College students: full course access; 13–15 have no cohort, 16 sits in cohort 1
(13, 'Marcus', 'Bell', 'marcus.bell@aari.org', @pw, 1, TRUE, NULL, 'Computer science junior taking the Orchestration track alongside my systems programming class.', 'software'),
(14, 'Aaliyah', 'Brooks', 'aaliyah.brooks@aari.org', @pw, 2, TRUE, NULL, 'Information systems senior using the Cloud Architect track for my capstone deployment.', NULL),
(15, 'Jordan', 'Hayes', 'jordan.hayes@aari.org', @pw, 3, TRUE, NULL, 'Electrical engineering student working ahead on Power Delivery load calculations.', NULL),
(16, 'Simone', 'Grant', 'simone.grant@aari.org', @pw, 2, TRUE, 1, 'College student auditing the Cloud Architect track with the Atlanta cohort.', NULL);

INSERT INTO `Week` (`weekid`, `courseid`, `subject`, `num`, `description`, `branch`) VALUES
(1, 1, 'What is a Data Center', 1, 'Data center purpose and scope, then C++ fundamentals: data types, I/O, variables, operators, and control flow with calculator projects.', 'shared'),
(2, 1, 'Abstraction: Loops, Functions & Classes', 2, 'Loops, arrays, functions, and OOP in C++ — Hangman and Tic-Tac-Toe raw builds before refactoring into classes.', 'shared'),
(3, 1, 'Low Level Computing', 3, 'Pointers, memory, bitwise networking, and computer architecture — terminal simulator, bit masking, and an 8-bit MIPS CPU simulator.', 'shared'),
(4, 1, 'Data Centers 101', 4, 'Compute, Linux, RAID, NFS, firewalls, virtualization, Proxmox, and Splunk — the shared infrastructure foundation before the curriculum branches.', 'shared'),
(5, 1, 'Web Development (Software Branch)', 5, 'Software branch: migrate C++ to JavaScript, build a dashboard shell in HTML/CSS, and integrate external APIs with security foundations.', 'software'),
(6, 1, 'Full Stack Engineering (Software Branch)', 6, 'Software branch capstone: Express backend, MySQL CRUD for server logs, and a normalized relational schema powering the monitoring dashboard.', 'software'),
(7, 1, 'Data Center Hardware (Hardware Branch)', 7, 'Hardware branch: rack architecture, spine-leaf networking, load balancing, and cooling systems for facility design.', 'hardware'),
(8, 1, 'Data Center Security (Hardware Branch)', 8, 'Hardware branch capstone: CIA triad, physical access control, IAM, SIEM, and incident response playbooks tied back to Week 4 NFS and RBAC.', 'hardware'),
(9, 2, 'Cloud Computing and Python Foundations', 1, 'IaaS/PaaS/SaaS, cloud benefits and tradeoffs, Python basics, and control flow — classify real apps and build calculator projects.', 'shared'),
(10, 2, 'Abstraction: Loops, Functions and Classes', 2, 'Loops, functions, and OOP in Python — Hangman and Tic-Tac-Toe raw builds, then an ordering platform with Customer, ServiceProvider, Inventory, and Order classes.', 'shared'),
(11, 2, 'Artificial Intelligence', 3, 'NumPy data representation, neural networks in Colab, LLMs, RAG with Ollama, and an industry chatbot on your ordering platform.', 'shared'),
(12, 2, 'Networking and Databases', 4, 'APIs, OSI model, remote LLM integration, MySQL CRUD for reviews, and a normalized customers/services/orders schema.', 'shared'),
(13, 2, 'Web Development', 5, 'Python to JavaScript, HTML/DOM wiring for the ordering UI, and Flask architecture connecting front end to backend.', 'shared'),
(14, 2, 'Cloud Computing and Community Cloud', 6, 'Azure migration (SQL, AI Foundry, MSAL), Docker and Azure Container Apps deployment, and the community cloud business proposal capstone.', 'shared'),
(15, 3, 'Electrical Fundamentals', 1, 'Charge, voltage, current, Ohm''s law, and power; series/parallel circuits, capacitors, inductors, diodes, and transistors with a breadboard lab; AC vs DC, three-phase, grounding, and electrical safety.', 'shared'),
(16, 3, 'Data Center Architecture', 2, 'CPU and memory hierarchy, PCI/NIC, motherboard, and GPU; LAN/WAN, switches, routers, firewalls, MAC vs IP, copper and fiber; racks, spine-leaf, STP, load balancing, and patch panels.', 'shared'),
(17, 3, 'Thermodynamics and Refrigeration', 3, 'Heat transfer and thermodynamics, the refrigeration cycle and COP, then data center cooling: CRAC vs home AC, DX vs chilled water, wet/dry towers, closed-loop systems, heat recovery, and Carnot limits.', 'shared'),
(18, 3, 'Energy Systems', 4, 'Power vs energy, transformers and batteries, fossil and renewable generation, the duck curve; wholesale/retail pricing, merit order, time-of-use and demand charges, LCOE; UPS, PDU, ATS, generators, PUE, and on-site solar.', 'shared'),
(19, 3, 'Python Foundations', 5, 'Python data types, print/input, variables, and operators with a terminal calculator; boolean logic and control flow with a menu; while/for loops, arrays, and a raw Hangman build.', 'shared'),
(20, 3, 'Environmental Monitoring and the Energy Dashboard', 6, 'Functions and a first sensor reading, polling loops with timestamped CSV logging and live PUE, then Flask JSON routes and a Chart.js energy dashboard capstone.', 'shared');

INSERT INTO `content` (`videoid`, `weekid`, `day`, `title`) VALUES
-- Orchestration weeks 1–4 (shared foundation)
(1, 1, 1, 'Session 1.1 & What is a Data Center'),
(2, 1, 2, 'Session 1.2 & C++: The Basics of Any Language'),
(3, 1, 3, 'Session 1.3 & Making Decisions: Logic and Control Flow'),
(4, 2, 1, 'Session 2.1 & Loops and Arrays'),
(5, 2, 2, 'Session 2.2 & Organizing Your Code: Functions'),
(6, 2, 3, 'Section 2.3 & Objects: Defining a Class in C++'),
(7, 3, 1, 'Section 3.1 & Pointers and Memory'),
(8, 3, 2, 'Section 3.2 & Bitwise Operators and Networking'),
(9, 3, 3, 'Section 3.3 & Computer Architecture'),
(10, 4, 1, 'Section 4.1 & Compute and Operating Systems'),
(11, 4, 2, 'Section 4.2 & Data Center Networking and Storage'),
(12, 4, 3, 'Section 4.3 & Virtualization'),
-- Orchestration weeks 5–6 (software branch)
(13, 5, 1, 'Section 5.1 & Migrating to JavaScript'),
(14, 5, 2, 'Session 5.2 & HTML and CSS'),
(15, 5, 3, 'Session 5.3 & APIs and Security Foundations'),
(16, 6, 1, 'Session 6.1 & Express and Web Security'),
(17, 6, 2, 'Session 6.2 & Databases I: Single Tables and CRUD'),
(18, 6, 3, 'Session 6.3 & Databases II: Relationships and Normalization'),
-- Orchestration weeks 7–8 (hardware branch)
(19, 7, 1, 'Section 5.1 & Data Center Architecture'),
(20, 7, 2, 'Section 5.2 & Network Infrastructure'),
(21, 7, 3, 'Section 5.3 & Cooling'),
(22, 8, 1, 'Section 6.1 & The Security Mindset and Core Concepts'),
(23, 8, 2, 'Section 6.2 & Physical Security and Access Control'),
(24, 8, 3, 'Section 6.3 & Identity, Monitoring, and Incident Response'),
-- Cloud Architect weeks 1–6
(25, 9, 1, 'Section 1.1 & What Is Cloud Computing?'),
(26, 9, 2, 'Session 1.2 & Python: The Basics of Any Language'),
(27, 9, 3, 'Session 1.3 & Making Decisions: Logic and Control Flow'),
(28, 10, 1, 'Session 2.1 & Loops'),
(29, 10, 2, 'Session 2.2 & Organizing Your Code: Functions'),
(30, 10, 3, 'Section 2.3 & Objects: Defining a Class in Python'),
(31, 11, 1, 'Session 3.1 & The Raw Material of AI: Data Representation'),
(32, 11, 2, 'Session 3.2 & How Models Learn: Neural Networks'),
(33, 11, 3, 'Session 3.3 & Large Language Models and RAG'),
(34, 12, 1, 'Session 4.1 & Networking and APIs'),
(35, 12, 2, 'Session 4.2 & Databases I: Single Tables and CRUD'),
(36, 12, 3, 'Session 4.3 & Databases II: Relationships and Normalization'),
(37, 13, 1, 'Section 5.1 & Migrating to JavaScript'),
(38, 13, 2, 'Session 5.2 & HTML and CSS: Building the Interface'),
(39, 13, 3, 'Session 5.3 & Software Architecture and Flask'),
(40, 14, 1, 'Section 6.1 & Transition to Cloud Using Azure'),
(41, 14, 2, 'Session 6.2 & Deployment'),
(42, 14, 3, 'Session 6.3 & Community Cloud: Technology as a Public Good'),
-- Power Delivery weeks 1–6
(43, 15, 1, 'Section 1.1 & Charge, Voltage, and Current'),
(44, 15, 2, 'Section 1.2 & Circuits and Components'),
(45, 15, 3, 'Section 1.3 & AC Power and Electrical Safety'),
(46, 16, 1, 'Section 2.1 & Computer Architecture'),
(47, 16, 2, 'Section 2.2 & Networking'),
(48, 16, 3, 'Section 2.3 & Data Center Architecture'),
(49, 17, 1, 'Section 3.1 & Heat and Energy Transfer'),
(50, 17, 2, 'Section 3.2 & The Refrigeration Cycle'),
(51, 17, 3, 'Section 3.3 & Cooling'),
(52, 18, 1, 'Section 4.1 & General Power Systems'),
(53, 18, 2, 'Section 4.2 & Energy and Electricity Pricing'),
(54, 18, 3, 'Section 4.3 & Power Delivery Systems for Data Centers'),
(55, 19, 1, 'Session 5.1 & Python: The Basics of Any Language'),
(56, 19, 2, 'Session 5.2 & Making Decisions: Logic and Control Flow'),
(57, 19, 3, 'Session 5.3 & Loops'),
(58, 20, 1, 'Section 6.1 & Functions and Your First Sensor Reading'),
(59, 20, 2, 'Section 6.2 & Data Collection and Logging'),
(60, 20, 3, 'Section 6.3 & Visualization and the Dashboard');

INSERT INTO `channel` (`channelid`, `cohortid`, `type`, `name`) VALUES
(1, 1, 'general', 'General'),
(2, 1, 'division', 'Data Center Orchestration'),
(3, 1, 'division', 'Cloud Architect'),
(4, 1, 'division', 'Power Delivery'),
(5, 1, 'direct', NULL),
(6, 1, 'direct', NULL),
(7, 2, 'general', 'General'),
(8, 2, 'division', 'Data Center Orchestration'),
(9, 2, 'division', 'Cloud Architect'),
(10, 2, 'division', 'Power Delivery'),
(11, 2, 'direct', NULL),
(12, 2, 'direct', NULL);

INSERT INTO `channel_member` (`channelid`, `member_type`, `member_id`) VALUES
(1, 'student', 1),
(1, 'student', 2),
(1, 'student', 3),
(1, 'student', 4),
(1, 'student', 5),
(1, 'student', 6),
(1, 'student', 16),
(1, 'leader', 1),
(1, 'admin', 1),
(7, 'student', 7),
(7, 'student', 8),
(7, 'student', 9),
(7, 'student', 10),
(7, 'student', 11),
(7, 'student', 12),
(7, 'leader', 2),
(7, 'admin', 1),
(2, 'student', 1),
(2, 'student', 2),
(2, 'leader', 1),
(3, 'student', 3),
(3, 'student', 4),
(3, 'student', 16),
(3, 'leader', 1),
(4, 'student', 5),
(4, 'student', 6),
(4, 'leader', 1),
(8, 'student', 7),
(8, 'student', 8),
(8, 'leader', 2),
(9, 'student', 9),
(9, 'student', 10),
(9, 'leader', 2),
(10, 'student', 11),
(10, 'student', 12),
(10, 'leader', 2),
(5, 'leader', 1),
(5, 'student', 1),
(6, 'leader', 1),
(6, 'student', 3),
(11, 'leader', 2),
(11, 'student', 7),
(12, 'leader', 2),
(12, 'student', 9);

INSERT INTO `messages` (`messagesid`, `channelid`, `sender_type`, `sender_id`, `content`, `sendtime`) VALUES
(1, 1, 'leader', 1, 'Welcome to Cohort 1! This program has three division tracks & Data Center Orchestration, Cloud Architect, and Power Delivery. General channel is for cross-track announcements.', '2026-01-06 09:00:00'),
(2, 1, 'admin', 1, 'Hi everyone & Sandra from platform ops. I drop org-wide updates here when we have community-cloud milestones.', '2026-01-06 09:15:00'),
(3, 1, 'student', 3, 'Cloud track checking in & finished my IaaS/PaaS/SaaS cloud audit for three tutoring apps. Feedback welcome in division channel.', '2026-01-06 14:22:00'),
(4, 1, 'leader', 1, 'Nice start David. Remember Week 1 Cloud goal: classify who manages what in the stack before you write backend code.', '2026-01-06 14:45:00'),
(5, 1, 'student', 1, 'Orchestration & anyone else stuck on the raw Hangman loop? My lives counter decrements twice sometimes.', '2026-01-07 11:03:00'),
(6, 4, 'student', 5, 'Power Delivery track & CRAC vs CRAH finally clicked when Patricia mapped it to our Atlanta humidity.', '2026-01-15 13:40:00'),
(7, 4, 'leader', 1, 'Great & facilities decisions directly affect the community cloud environmental profile.', '2026-01-15 14:02:00'),
(8, 2, 'student', 1, 'RAID lab done in VirtualBox. mdadm survived my simulated disk pull & satisfying.', '2026-01-16 08:55:00'),
(9, 2, 'student', 2, 'C++ to JS port is weirdly fun. Hangman reads the same but console.log beats cout for quick tests.', '2026-01-16 09:12:00'),
(10, 3, 'student', 4, 'Flask /services and /order routes working. My front-end fetch finally returns JSON from the ordering platform instead of hardcoded arrays.', '2026-01-20 17:30:00'),
(11, 3, 'leader', 1, 'That is the Week 5 Cloud milestone & share your repo link in division if you want peer review.', '2026-01-20 17:44:00'),
(12, 5, 'student', 1, 'Thanks for the DM Denise & submitting orchestration capstone tonight.', '2026-01-21 19:05:00'),
(13, 5, 'leader', 1, 'Tag me if the Express dashboard JOIN query gets confusing.', '2026-01-21 19:11:00'),
(14, 7, 'leader', 2, 'Cohort 2 welcome! Same three tracks & check your division channel for track-specific labs.', '2026-01-06 09:00:00'),
(15, 7, 'student', 7, 'Orchestration here. Bit masking project & my network address output is off by one on broadcast. Common mistake?', '2026-01-08 12:20:00'),
(16, 7, 'leader', 2, 'Check your AND mask on the host bits & rewatch Session 2.3 binary segment.', '2026-01-08 12:35:00'),
(17, 7, 'student', 11, 'Power Delivery track & when do we walk the actual cohort lab space? Need to validate aisle layout.', '2026-01-09 15:00:00'),
(18, 7, 'leader', 2, 'Facilities walkthrough is Week 6 capstone. Weeks 1 & 5 are async videos plus optional sync Q&A.', '2026-01-09 15:18:00'),
(19, 10, 'student', 11, 'N+1 power analysis & is generator capacity separate from UPS sizing in the rubric?', '2026-01-17 11:45:00'),
(20, 10, 'leader', 2, 'Separate sections. UPS covers ride-through; generator is extended outage & show both calculations.', '2026-01-17 12:00:00'),
(21, 9, 'student', 9, 'RAG chatbot returning generic answers & how many markdown files minimum for knowledge base?', '2026-01-18 16:22:00'),
(22, 9, 'student', 10, 'I used five short docs on auto repair services. Quality beats quantity.', '2026-01-18 16:40:00'),
(23, 8, 'student', 8, 'Express /servers route done. Dashboard cards pull live JSON & feels like real orchestration work.', '2026-01-19 09:30:00'),
(24, 8, 'leader', 2, 'That is the Week 6 orchestration target. Next step: normalized logs schema with JOINs.', '2026-01-19 09:48:00'),
(25, 10, 'student', 12, 'Sustainability profile draft done & heat recovery section was the hardest part.', '2026-01-19 14:15:00'),
(26, 1, 'student', 3, 'Cloud track & Azure Container Apps deploy worked. Public URL in my assignment submission.', '2026-01-22 18:00:00'),
(27, 1, 'student', 5, 'Energy + Cloud overlap on community cloud environmental commitments is interesting & reading both tracks.', '2026-01-22 18:12:00'),
(28, 4, 'student', 6, 'Hot aisle containment question: partial vs full containment for our small lab?', '2026-01-21 10:00:00'),
(29, 2, 'leader', 1, 'Orchestration & save VirtualBox snapshots before RAID failure simulation. Makes retry faster.', '2026-01-23 08:30:00'),
(30, 11, 'leader', 2, 'Brian & bit masking question answered in DM. Office hours tomorrow if still stuck.', '2026-01-15 21:00:00'),
(31, 11, 'student', 7, 'Will do, thanks Robert.', '2026-01-15 21:04:00'),
(32, 2, 'student', 2, 'Finished NFS lab. Mount works but only after I fixed rpcbind & worth adding to FAQ.', '2026-01-22 07:50:00'),
(33, 7, 'admin', 1, 'Org-wide reminder: community cloud governance workshop is mandatory for all tracks before build week.', '2026-01-24 08:00:00');