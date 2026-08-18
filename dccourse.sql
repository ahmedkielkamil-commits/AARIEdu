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

CREATE DATABASE IF NOT EXISTS `dccourse` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE `dccourse`;
SET NAMES utf8mb4;

-- Drop children before parents (FK order)
DROP TABLE IF EXISTS `messages`;
DROP TABLE IF EXISTS `channel_member`;
DROP TABLE IF EXISTS `assignment`;
DROP TABLE IF EXISTS `progress`;
DROP TABLE IF EXISTS `video`;
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
-- division-tracks (courses), weekly video lessons, graded assignments,
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

-- Platform course admins: author weeks/videos across all division tracks (not cohort-scoped).
CREATE TABLE `admin` (
    `adminid`  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `fname`    VARCHAR(255) NOT NULL,
    `lname`    VARCHAR(255) NOT NULL,
    `email`    VARCHAR(255) NOT NULL,
    `password` VARCHAR(255) NOT NULL,  -- bcrypt hash
    UNIQUE KEY `admin_email_unique` (`email`)
);

CREATE TABLE `leader` (
    `leaderid`  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `fname`     VARCHAR(255) NOT NULL,
    `lname`     VARCHAR(255) NOT NULL,
    `email`     VARCHAR(255) NOT NULL,
    `password`  VARCHAR(255) NOT NULL,  -- bcrypt hash
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
    `password`  VARCHAR(255) NOT NULL,  -- bcrypt hash
    `courseid`  BIGINT UNSIGNED NOT NULL,  -- division assignment
    `cohortid`  BIGINT UNSIGNED NOT NULL,
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

CREATE TABLE `video` (
    `videoid`      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `weekid`       BIGINT UNSIGNED NOT NULL,
    `day`          TINYINT UNSIGNED NOT NULL,  -- lecture day within the week (1 & 3)
    `title`        VARCHAR(255) NOT NULL,
    `miniokey`     VARCHAR(255) NOT NULL,  -- MinIO object key (streaming handled later)
    `script`       TEXT NOT NULL,
    `instructions` TEXT NOT NULL,          -- what students submit (deliverable instructions)
    `reflection`   TEXT NOT NULL,          -- instructor reflection on the assignment
    CONSTRAINT `video_weekid_fk` FOREIGN KEY (`weekid`) REFERENCES `Week` (`weekid`)
);

-- Graded assignment submission, one per (student, video) attempt.
CREATE TABLE `assignment` (
    `assignmentid` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `videoid`      BIGINT UNSIGNED NOT NULL,
    `studentid`    BIGINT UNSIGNED NOT NULL,
    `miniokey`     VARCHAR(255) NOT NULL,  -- submitted file in MinIO
    `status`       ENUM('submitted','satisfactory','unsatisfactory') NOT NULL DEFAULT 'submitted',
    `feedback`     VARCHAR(255) NULL,       -- admin's written feedback; null until graded
    `submitted_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT `assignment_videoid_fk` FOREIGN KEY (`videoid`) REFERENCES `video` (`videoid`),
    CONSTRAINT `assignment_studentid_fk` FOREIGN KEY (`studentid`) REFERENCES `student` (`studentid`)
);

-- Video watch progress, one row per (student, video).
CREATE TABLE `progress` (
    `studentid`     BIGINT UNSIGNED NOT NULL,
    `videoid`       BIGINT UNSIGNED NOT NULL,
    `watched`       BOOLEAN NOT NULL DEFAULT FALSE,
    `last_position` INT UNSIGNED NOT NULL DEFAULT 0,  -- seconds into the video (resume point)
    `updated_at`    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`studentid`, `videoid`),
    CONSTRAINT `progress_studentid_fk` FOREIGN KEY (`studentid`) REFERENCES `student` (`studentid`),
    CONSTRAINT `progress_videoid_fk` FOREIGN KEY (`videoid`) REFERENCES `video` (`videoid`)
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


-- ============================================================
-- Seed data (local development)
-- Curriculum: Data Center Orchestration (8 weeks, branching),
-- Cloud Architect, Electrical Engineering (6 weeks × 3 sessions each)
-- Use: python make_test_login.py --suite dc --reset-all
-- ============================================================

SET @pw = '123123';

INSERT INTO `Course` (`courseid`, `name`, `description`, `teacher`) VALUES
(1, 'Data Center Orchestration', 'Eight-week branching track for the data center: four shared foundation weeks, then two software weeks (web development and full-stack monitoring) and two hardware weeks (facility architecture and security). From C++ and low-level computing through Proxmox, Express, MySQL, spine-leaf design, and incident response.', 'Ahmed Kiel-Kamil'),
(2, 'Cloud Architect', 'Six-week path from cloud fundamentals and Python through AI/RAG, Flask/MySQL, JavaScript front ends, Azure deployment, and a community cloud business proposal — building ordering platforms local businesses can actually use.', 'Ahmed Kiel-Kamil'),
(3, 'Electrical Engineering', 'Six-week track from Ohm''s law and breadboard circuits through data center architecture, thermodynamics, cooling, energy pricing, and a Python/Flask energy monitoring dashboard capstone — the physical infrastructure foundation for the community cloud.', 'Ahmed Kiel-Kamil');

INSERT INTO `cohort` (`cohortid`, `region`, `name`) VALUES
(1, 'Atlanta', 'Cohort 1'),
(2, 'Atlanta', 'Cohort 2');

INSERT INTO `admin` (`adminid`, `fname`, `lname`, `email`, `password`) VALUES
(1, 'Sandra',  'Ellis',  'sandra.ellis@aari.org',   @pw),
(2, 'Ahmed',   'Kiel-Kamil', 'ahmed.kiel@aari.org', @pw);

INSERT INTO `leader` (`leaderid`, `fname`, `lname`, `email`, `password`, `cohortid`, `bio`) VALUES
(1, 'Denise', 'Parker', 'denise.parker@aari.org', @pw, 1, 'Cohort 1 leader — cross-track support, grading, and cohort chat.'),
(2, 'Robert', 'Kim', 'robert.kim@aari.org', @pw, 2, 'Cohort 2 leader — cross-track support and grading.');

INSERT INTO `student` (`studentid`, `fname`, `lname`, `email`, `password`, `courseid`, `cohortid`, `bio`, `orchestration_branch`) VALUES
(1, 'James', 'Porter', 'james.porter@aari.org', @pw, 1, 1, 'Orchestration software specialist - building the Splunk monitoring dashboard.', 'software'),
(2, 'Keisha', 'Williams', 'keisha.williams@aari.org', @pw, 1, 1, 'Porting C++ Hangman to JavaScript this week.', 'software'),
(3, 'David', 'Nguyen', 'david.nguyen@aari.org', @pw, 2, 1, 'Cloud Architect — building a tutoring-industry ordering platform with Customer, ServiceProvider, and Order classes.', NULL),
(4, 'Angela', 'Martinez', 'angela.martinez@aari.org', @pw, 2, 1, 'Working on Flask + MySQL reviews table for my service-ordering app.', NULL),
(5, 'Terrence', 'Jackson', 'terrence.jackson@aari.org', @pw, 3, 1, 'Electrical Engineering track — working through circuit analysis before sizing cohort rack loads.', NULL),
(6, 'Michelle', 'Chen', 'michelle.chen@aari.org', @pw, 3, 1, 'Drafting spine-leaf and hot/cold aisle layouts for our Atlanta facility.', NULL),
(7, 'Brian', 'O''Connor', 'brian.oconnor@aari.org', @pw, 1, 2, 'RAID lab in VirtualBox - orchestration track.', 'hardware'),
(8, 'Renee', 'Foster', 'renee.foster@aari.org', @pw, 1, 2, 'Express dashboard connecting to /servers API.', 'software'),
(9, 'Carlos', 'Rivera', 'carlos.rivera@aari.org', @pw, 2, 2, 'RAG chatbot for auto-repair industry on my community-cloud site.', NULL),
(10, 'Nicole', 'Adams', 'nicole.adams@aari.org', @pw, 2, 2, 'Deploying the ordering platform to Azure Container Apps with Docker and MSAL auth.', NULL),
(11, 'Kevin', 'Patel', 'kevin.patel@aari.org', @pw, 3, 2, 'Electrical Engineering - power redundancy analysis for cohort pod, N+1 calculations.', NULL),
(12, 'Jasmine', 'Wright', 'jasmine.wright@aari.org', @pw, 3, 2, 'Building the Python/Flask energy dashboard — live PUE charts from simulated PDU sensors.', NULL);

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
(15, 3, 'Electrical Fundamentals', 1, 'Charge, voltage, current, Ohm''s law, series/parallel circuits, components, AC power, and electrical safety — quantitative foundations for every power and cooling decision.', 'shared'),
(16, 3, 'Data Center Architecture', 2, 'Computer architecture, networking, racks and rails, spine-leaf topology, and physical infrastructure — connecting electronics to facility design.', 'shared'),
(17, 3, 'Thermodynamics and Refrigeration', 3, 'Heat transfer, refrigeration cycle, server heat management, heatsinks, and aisle containment — every watt in becomes heat out.', 'shared'),
(18, 3, 'Data Center Cooling', 4, 'DX vs chilled water, WUE and closed-loop systems, evaporative cooling in Atlanta humidity, and ORC heat recovery.', 'shared'),
(19, 3, 'Energy Systems', 5, 'Power vs energy, grid pricing, merit order, demand charges, UPS/PDU/ATS/generator chain, PUE, and on-site solar integration.', 'shared'),
(20, 3, 'Environmental Monitoring and the Energy Dashboard', 6, 'Sensors, CSV logging, live PUE/WUE calculation, Flask APIs, and a browser-based energy dashboard capstone.', 'shared');

INSERT INTO `video` (`videoid`, `weekid`, `day`, `title`, `miniokey`, `script`, `instructions`, `reflection`) VALUES
-- Orchestration weeks 1–4 (shared foundation)
(1, 1, 1, 'Session 1.1 & What is a Data Center', 'videos/orchestration/wk1_sec11.mp4', 'Purpose of a data center; compute, storage, and networking at facility scale; how software and hardware roles divide in the cohort build.', 'Write a half-page overview of one community-cloud workload (web app, file share, or monitoring) and which physical systems it depends on.', 'This week anchors every later topic — software students and hardware students share the same vocabulary for what we are building.'),
(2, 1, 2, 'Session 1.2 & C++: The Basics of Any Language', 'videos/orchestration/wk1_sec12.mp4', 'Data types (int, float, char, bool, string); cin/cout I/O; variables; arithmetic and assignment operators.', 'Build a terminal calculator in C++ that reads two numbers via cin and prints results for +, −, ×, and ÷ as separate operations.', 'C++ syntax transfers to every systems language you will touch — focus on reading compiler errors, not memorizing keywords.'),
(3, 1, 3, 'Session 1.3 & Making Decisions: Logic and Control Flow', 'videos/orchestration/wk1_sec13.mp4', 'Boolean logic (&&, ||, !); comparison operators; if/else chains; nested conditionals; switch statements.', 'Upgrade your calculator with a menu (add/subtract/multiply/divide) using switch or if/else, and guard division by zero with a friendly error message.', 'Control flow is how programs make decisions — the same patterns appear in firewall rules and orchestration scripts later.'),
(4, 2, 1, 'Session 2.1 & Loops and Arrays', 'videos/orchestration/wk2_sec21.mp4', 'Why repetition matters; while and for loops; infinite-loop pitfalls; arrays, indexing, and iterating with loops.', 'Build raw Hangman in one C++ block: hardcoded char array, guess loop, lives counter, win/lose detection — intentionally messy.', 'Hangman teaches iteration before abstraction — you will refactor this pattern into functions and classes this week.'),
(5, 2, 2, 'Session 2.2 & Organizing Your Code: Functions', 'videos/orchestration/wk2_sec22.mp4', 'Functions, parameters, return values, scope, and DRY — large programs as many small functions working together.', 'Build two-player Tic-Tac-Toe in one unstructured block with win/draw detection and a running scoreboard across rematches.', 'Like Hangman, Tic-Tac-Toe stays monolithic on purpose — next session you refactor into a class and feel why structure matters.'),
(6, 2, 3, 'Section 2.3 & Objects: Defining a Class in C++', 'videos/orchestration/wk2_sec23.mp4', 'Member variables and functions; constructors (default, parameterized, copy); encapsulation; getters and setters.', 'Refactor Tic-Tac-Toe into a Game class with private board state and public methods for play(), checkWinner(), and reset().', 'Classes are how you model servers, VMs, and logs in code — this is the same abstraction the dashboard uses in JavaScript later.'),
(7, 3, 1, 'Section 3.1 & Pointers and Memory', 'videos/orchestration/wk3_sec11.mp4', 'RAM vs ROM; NVMe/SSD/HDD; pointers and dynamic allocation (new/delete); file streams for disk I/O.', 'Build a terminal simulator (ls, cd, mkdir, touch) using a tree of directories connected by pointers.', 'Pointers mirror how the OS tracks open files and processes — the terminal simulator is a miniature file system.'),
(8, 3, 2, 'Section 3.2 & Bitwise Operators and Networking', 'videos/orchestration/wk3_sec12.mp4', 'Ports; PAN/LAN/WAN scope; switches, WAPs, and fiber; IP vs MAC addressing; bitwise ops and bit shifting; DNS, TCP/UDP, HTTP/HTTPS.', 'Write a C++ subnet calculator: user enters IP and mask in binary; program prints network, host, and broadcast addresses using bitwise AND.', 'Bit masking is how routers decide which packets stay local — you will read these numbers in Kali captures next week.'),
(9, 3, 3, 'Section 3.3 & Computer Architecture', 'videos/orchestration/wk3_sec13.mp4', 'CPU fetch-decode-execute; motherboard; cores and chips; instruction decoding; GPUs for parallel and AI workloads.', 'Implement a simplified 8-bit MIPS simulator supporting ADD, SUB, LOAD, and STORE against a register file and memory array.', 'Understanding the pipeline explains why monitoring CPU vs GPU utilization matters in a real data center.'),
(10, 4, 1, 'Section 4.1 & Compute and Operating Systems', 'videos/orchestration/wk4_sec11.mp4', 'Server form factors; ECC and redundancy; process and memory management; Linux history and distros (Ubuntu, Debian, RHEL).', 'On a Linux VM, write a shell script using top, ps, free, and df that prints a readable system dashboard each run.', 'Pulling live metrics from the OS is the primitive version of the Splunk dashboard you build by Week 4 day 3.'),
(11, 4, 2, 'Section 4.2 & Data Center Networking and Storage', 'videos/orchestration/wk4_sec12.mp4', 'RAID; NAS vs SAN; UFW/iptables; NFS; mdadm; OSI model; Kali Linux for packet capture with Wireshark/tcpdump.', 'Configure mdadm RAID, NFS between two VMs, iptables allowing only NFS, then capture and annotate traffic layers in Kali.', 'Watching packets in Kali makes the OSI model concrete — save your captures for the spine-leaf design in the hardware branch.'),
(12, 4, 3, 'Section 4.3 & Virtualization', 'videos/orchestration/wk4_sec13.mp4', 'RHEL enterprise support; hypervisors; vertical vs horizontal scaling; Proxmox; iDRAC out-of-band management; Splunk log aggregation.', 'Deploy two VMs in Proxmox, simulate a failure on one, ingest logs into Splunk, and build a dashboard showing CPU, memory, and uptime.', 'Virtualization containment is the story of the software branch — monitoring proves the surviving VM never noticed the failure.'),
-- Orchestration weeks 5–6 (software branch)
(13, 5, 1, 'Section 5.1 & Migrating to JavaScript', 'videos/orchestration/wk5_sec11.mp4', 'Syntax differences from C++; dynamic arrays/objects; let/const; functions and control flow; JSON as structured data on the wire.', 'Port your C++ calculator or Hangman to JavaScript and run it in the browser console — same logic, new syntax.', 'The concepts transfer; only the syntax changes — this session bridges systems programming to web orchestration.'),
(14, 5, 2, 'Session 5.2 & HTML and CSS', 'videos/orchestration/wk5_sec12.mp4', 'HTML element tree; core tags; DOM as objects (getElementById, querySelector); innerHTML/events; box model; linking .js files.', 'Build the HTML/CSS shell of a server monitoring dashboard: header, grid of hardcoded server cards, sidebar of VMs — data in JS objects for now.', 'Your C++ classes become JavaScript objects in the browser — structure mirrors the Week 3 OOP work.'),
(15, 5, 3, 'Session 5.3 & APIs and Security Foundations', 'videos/orchestration/wk5_sec13.mp4', 'Remote APIs and fetch(); CIA triad; threat vs vulnerability vs risk; attack surface; defense in depth; least privilege and zero trust.', 'Add a live external API call to your dashboard; store the API key in an environment variable and document what happens if it is exposed client-side vs server-side.', 'This session is the deliberate bridge into Express — credentials belong behind a backend, not in the browser.'),
(16, 6, 1, 'Session 6.1 & Express and Web Security', 'videos/orchestration/wk6_sec11.mp4', 'Express routes and routers; .env secrets; Helmet headers; express-rate-limit; CORS as a security boundary.', 'Replace hardcoded dashboard data with fetch() to Express /servers and /vms routes; move API keys server-side; add rate limiting and CORS whitelist.', 'Every control from Session 5.3 gets applied to a real backend — this is defense in depth in code.'),
(17, 6, 2, 'Session 6.2 & Databases I: Single Tables and CRUD', 'videos/orchestration/wk6_sec12.mp4', 'Why files fail at scale; relational tables; MySQL Workbench; INSERT/SELECT/UPDATE/DELETE; aggregates; connecting Express to MySQL.', 'Add a logs table; build Express routes that INSERT on status change and SELECT history for a clicked server; show log panel in the dashboard.', 'Persistent logs turn a pretty dashboard into an auditable operations tool.'),
(18, 6, 3, 'Session 6.3 & Databases II: Relationships and Normalization', 'videos/orchestration/wk6_sec13.mp4', 'Primary/foreign keys; one-to-one, one-to-many, many-to-many; junction tables; 1NF–3NF; INNER and LEFT JOIN; schema design first.', 'Normalize into servers, virtual_machines, and logs tables; write JOINs for VMs per server and logs per VM; update dashboard to drill down server → VM → log history.', 'Software branch capstone: a database-backed monitoring tool you built end to end.'),
-- Orchestration weeks 7–8 (hardware branch)
(19, 7, 1, 'Section 5.1 & Data Center Architecture', 'videos/orchestration/wk7_sec11.mp4', 'Two-post vs four-post racks; rack units (U); sliding rails; structured cable management; rack PDUs with remote monitoring.', 'Upload a rack elevation diagram: network rack vs compute rack, PDU placement, patch panel, and labeled cable paths.', 'Physical layout is a security and cooling control — tangled cabling hides problems and blocks airflow.'),
(20, 7, 2, 'Section 5.2 & Network Infrastructure', 'videos/orchestration/wk7_sec12.mp4', 'Access/aggregation/core hierarchy; L2 vs L3 vs multilayer switches; northbound/southbound/east-west traffic; spine-leaf; STP; load balancing; patch panels.', 'Sketch a spine-leaf pod for six servers: label spine and leaf switches, one east-west path, one northbound path, and note STP-blocked redundant links.', 'East-west dominates modern DC traffic — your spine-leaf sketch should show two-hop paths clearly.'),
(21, 7, 3, 'Section 5.3 & Cooling', 'videos/orchestration/wk7_sec13.mp4', 'DX/CRAC; chilled water/CRAH; dry cooling towers; heat recovery; cold/hot aisle containment; raised-floor grilles.', 'Upload a floor plan with cold/hot aisles, CRAC placement, floor grilles, and total cooling capacity vs rack TDP.', 'Cooling choices tie directly to the Electrical Engineering track — document assumptions for cross-track review.'),
(22, 8, 1, 'Section 6.1 & The Security Mindset and Core Concepts', 'videos/orchestration/wk8_sec11.mp4', 'CIA triad; threat, vulnerability, and risk; attack surface reduction; defense in depth; least privilege; zero trust.', 'Pick one cohort service (web app, NFS share, or SSH admin) and write a half-page threat model with one control per CIA pillar.', 'Threat modeling decides which controls earn their complexity — draft this before writing firewall rules.'),
(23, 8, 2, 'Section 6.2 & Physical Security and Access Control', 'videos/orchestration/wk8_sec12.mp4', 'Physical security as first layer; access zones; layered authentication; mantraps; CCTV and audit logging; rack-level locks.', 'Create a facilities access matrix: zones (perimeter, floor, rack) × roles (technician, admin, visitor) with required auth per cell.', 'If an attacker reaches the rack, network controls matter less — physical zones are your outermost firewall.'),
(24, 8, 3, 'Section 6.3 & Identity, Monitoring, and Incident Response', 'videos/orchestration/wk8_sec13.mp4', 'IAM and RBAC; MFA; RBAC callback to NFS permissions; SIEM aggregation; log integrity; incident response phases; backup and recovery testing.', 'Write a one-page incident response outline for suspected SSH brute-force (identify, contain, eradicate, recover, lessons learned) and map RBAC roles to your Week 4 NFS exports.', 'Hardware branch capstone: security operations tied back to the infrastructure you configured in Week 4.'),
(25, 9, 1, 'Section 1.1 & What Is Cloud Computing?', 'videos/cloud/wk1_sec11.mp4', 'Frontend, backend, and infrastructure layers; cloud as enterprise infrastructure; IaaS, PaaS, SaaS; cloud benefits and disadvantages including vendor lock-in and environmental cost.', 'Pick three apps you use daily; classify each as IaaS, PaaS, or SaaS with one-sentence justification; sketch a three-layer diagram for your most interesting app.', 'The community cloud model at the end of this course directly addresses the disadvantages you identify here.'),
(26, 9, 2, 'Session 1.2 & Python: The Basics of Any Language', 'videos/cloud/wk1_sec12.mp4', 'Python data types; print/input I/O; variables; arithmetic and assignment operators.', 'Build a terminal calculator in Python that reads two numbers and prints results for all four basic operations.', 'Python is the backend language for Flask, AI routes, and Azure migration — master I/O before APIs.'),
(27, 9, 3, 'Session 1.3 & Making Decisions: Logic and Control Flow', 'videos/cloud/wk1_sec13.mp4', 'Boolean logic; comparison operators; if/elif/else chains; nested conditionals.', 'Upgrade your calculator with an operation menu using if/else or match, and guard division by zero with a friendly error.', 'Control flow patterns reappear in Flask route logic and chatbot prompt routing later.'),
(28, 10, 1, 'Session 2.1 & Loops', 'videos/cloud/wk2_sec21.mp4', 'Why repetition matters; while and for loops; infinite-loop pitfalls; lists, indexing, and iteration.', 'Build raw Hangman in one Python block: hardcoded word, guess loop, lives counter, win/lose detection — intentionally messy.', 'Hangman teaches iteration before functions — the same pattern powers polling loops in your energy peers'' dashboards.'),
(29, 10, 2, 'Session 2.2 & Organizing Your Code: Functions', 'videos/cloud/wk2_sec22.mp4', 'Functions, parameters, return values, scope, and DRY — programs as many small functions.', 'Build two-player Tic-Tac-Toe in one unstructured block with win/draw detection and a running scoreboard across rematches.', 'Monolithic on purpose — next session you model the same ideas as classes for the ordering platform.'),
(30, 10, 3, 'Section 2.3 & Objects: Defining a Class in Python', 'videos/cloud/wk2_sec23.mp4', 'Member variables and methods; constructors; encapsulation; getters and setters.', 'Build a terminal ordering platform with Customer, ServiceProvider, Inventory, and Order classes; place orders and print histories from both perspectives.', 'These four classes become your database schema in Week 4 — design them carefully now.'),
(31, 11, 1, 'Session 3.1 & The Raw Material of AI: Data Representation', 'videos/cloud/wk3_sec31.mp4', 'Scalars, vectors, matrices; NumPy; normalization and one-hot encoding; annotations; images as pixel matrices; Pandas CSV basics.', 'Run the Colab image classifier on industry photos; upload screenshots with three predictions and confidence scores.', 'AI starts with numbers — your industry images are matrices before they are categories.'),
(32, 11, 2, 'Session 3.2 & How Models Learn: Neural Networks', 'videos/cloud/wk3_sec32.mp4', 'Layers, weights, biases; ReLU/sigmoid/softmax; forward pass; loss functions; backprop and gradient descent; overfitting vs underfitting.', 'Train a small neural network in Colab on a domain dataset; adjust learning rate and epochs; upload loss/accuracy plot.', 'Understanding training loops explains why hosted LLM APIs charge per token — compute has a cost.'),
(33, 11, 3, 'Session 3.3 & Large Language Models and RAG', 'videos/cloud/wk3_sec33.mp4', 'LLMs and tokenization; system prompts and fine-tuning; RAG pipeline; Ollama local models; vector databases conceptually.', 'Add an Ollama-powered industry chatbot to your platform: Flask route, markdown knowledge base, RAG prompt injection, simple chat UI.', 'Your first AI feature on a real product — the chatbot should know your industry, not generic facts.'),
(34, 12, 1, 'Session 4.1 & Networking and APIs', 'videos/cloud/wk4_sec11.mp4', 'Local libraries to remote APIs; network scope; REST/HTTP/TCP/UDP/WebSockets; IP, ports, DNS; TLS/HTTPS/VPN; packets and OSI model.', 'Replace local Ollama with OpenAI or Hugging Face Inference API; store API key in .env; handle rate limits and errors gracefully.', 'First paid remote API call — authentication and error handling matter as much as the model response.'),
(35, 12, 2, 'Session 4.2 & Databases I: Single Tables and CRUD', 'videos/cloud/wk4_sec21.mp4', 'Relational tables; mapping Python classes to tables; INSERT/SELECT/UPDATE/DELETE; aggregates; Flask + mysql-connector-python.', 'Add a reviews table (reviewer, service, rating, comment, timestamp); build Flask INSERT and SELECT routes; add review form and display on front end.', 'Persistent reviews prove your platform serves real customers — not just demo data in memory.'),
(36, 12, 3, 'Session 4.3 & Databases II: Relationships and Normalization', 'videos/cloud/wk4_sec31.mp4', 'Redundancy problems; primary/foreign keys; one-to-one, one-to-many, many-to-many; 1NF–3NF; INNER/LEFT JOIN; schema design first.', 'Normalize into customers, services, and orders junction tables; write JOINs for customer order history and service popularity; update Flask routes.', 'Your Week 2 object model now lives in MySQL — JOINs are how you query it efficiently.'),
(37, 13, 1, 'Section 5.1 & Migrating to JavaScript', 'videos/cloud/wk5_sec11.mp4', 'Syntax differences from Python; dynamic typing; let/const; functions and control flow; JSON on the wire.', 'Port your ordering platform logic from Python to JavaScript and run it in the browser console.', 'Same concepts, new syntax — this session bridges your Python backend to a browser front end.'),
(38, 13, 2, 'Session 5.2 & HTML and CSS: Building the Interface', 'videos/cloud/wk5_sec21.mp4', 'HTML element tree; core tags; DOM as objects (getElementById, querySelector); innerHTML/events; linking .js files.', 'Wire your JavaScript ordering platform to HTML: inventory cards, place-order flow, customer and vendor order history — functional but unstyled.', 'Focus on DOM wiring now; CSS styling can come after the event handlers work reliably.'),
(39, 13, 3, 'Session 5.3 & Software Architecture and Flask', 'videos/cloud/wk5_sec31.mp4', 'Flask routes and jsonify; templating, CORS, sessions; GitHub README; layered, onion, modular monolith, CQRS, and service-oriented patterns.', 'Set up Flask /services and /order routes; connect front-end fetch() to local Flask instead of hardcoded data; push to GitHub with architecture README.', 'Your ordering platform now has a real backend — document the pattern you chose and why.'),
(40, 14, 1, 'Section 6.1 & Transition to Cloud Using Azure', 'videos/cloud/wk6_sec11.mp4', 'Azure AD service principals; rate limiting; Azure SQL; Azure AI Foundry model catalog; MSAL authentication and RBAC.', 'Migrate MySQL to Azure SQL, LLM to Azure AI Foundry, add MSAL auth with student/tutor roles — no local dependencies remaining.', 'Every local service gets an Azure equivalent — map each component before you migrate.'),
(41, 14, 2, 'Session 6.2 & Deployment', 'videos/cloud/wk6_sec21.mp4', 'Docker containers; reverse proxies; Kubernetes scaling; Azure Container Apps with KEDA scale-to-zero.', 'Containerize Flask with Dockerfile; configure reverse proxy; deploy full stack to Azure Container Apps; upload live public URL and README architecture diagram.', 'Container Apps is production infrastructure without managing Kubernetes yourself — treat the URL like a real launch.'),
(42, 14, 3, 'Session 6.3 & Community Cloud: Technology as a Public Good', 'videos/cloud/wk6_sec31.mp4', 'Data center environmental cost; digital gravity and lock-in; infinite upscale problem; community cloud model; nonprofit governance and business strategy.', 'Draft a community cloud business proposal: three to five services your industry needs beyond your build, governance structure, environmental commitments, and pitch.', 'Capstone: reframe your deployed app as the seed of a locally owned platform — not a generic SaaS clone.'),
(43, 15, 1, 'Section 1.1 & Charge, Voltage, and Current', 'videos/energy/wk1_sec11.mp4', 'Electric charge; voltage as potential difference; current in amperes; resistance and Ohm''s law (V = IR); power P = IV and heat generation in circuits.', 'Upload worked circuit analysis: voltage drops, branch currents, and heat dissipation for at least three circuits using V = IR and P = IV.', 'Every rack power budget starts with Ohm''s law — show units on every step.'),
(44, 15, 2, 'Section 1.2 & Circuits and Components', 'videos/energy/wk1_sec12.mp4', 'Series vs parallel circuits; capacitors and inductors; diodes and AC-to-DC conversion; transistors as switches.', 'Build a breadboard circuit (LED, resistor, switch); upload multimeter readings at two points verifying your hand calculations.', 'If measured values disagree with calculations by more than 10%, find the wiring or math error before moving on.'),
(45, 15, 3, 'Section 1.3 & AC Power and Electrical Safety', 'videos/energy/wk1_sec13.mp4', 'AC vs DC; 60 Hz frequency and RMS voltage; three-phase power; grounding and bonding; electrical safety and lethal current.', 'Complete the AC safety checklist; upload signed acknowledgment and one paragraph on why three-phase matters for data center feeds.', 'High current kills — safety procedures are non-negotiable before live PDU work.'),
(46, 16, 1, 'Section 2.1 & Computer Architecture', 'videos/energy/wk2_sec21.mp4', 'CPU execution; RAM vs ROM; memory hierarchy (registers, cache, NVMe/SSD/HDD); PCI and NIC; motherboard buses; GPU parallel workloads.', 'Calculate total TDP for a 10-server rack from spec-sheet values; show sum and identify the largest heat contributor.', 'TDP drives cooling sizing — this bridges electronics to Week 3 heat management.'),
(47, 16, 2, 'Section 2.2 & Networking', 'videos/energy/wk2_sec22.mp4', 'LAN vs WAN; switches vs routers vs firewalls; MAC (Layer 2) vs IP (Layer 3) addressing; radio waves and WiFi; Cat6A copper vs fiber optics.', 'Upload a diagram labeling MAC vs IP roles on one server path from NIC to router, noting where each address type is used.', 'Networking vocabulary from this week feeds directly into spine-leaf design in the next session.'),
(48, 16, 3, 'Section 2.3 & Data Center Architecture', 'videos/energy/wk2_sec23.mp4', 'Server redundancy (ECC, expansion cards); racks, U space, rails, blanking panels; access/aggregation/core hierarchy; L2/L3/Nexus switches; north/south/east-west traffic; spine-leaf; STP; load balancing; patch panels.', 'Upload a rack elevation and spine-leaf sketch for six servers: label ToR switches, one east-west and one northbound path, and STP-blocked redundant links.', 'East-west dominates modern DC traffic — your sketch should show two-hop paths clearly.'),
(49, 17, 1, 'Section 3.1 & Heat and Energy Transfer', 'videos/energy/wk3_sec31.mp4', 'Thermal vs kinetic energy; conduction, convection, radiation; first and second laws of thermodynamics; Q/t = kAΔT/d; specific heat Q = mcΔT.', 'Upload thermal worksheet: wall heat loss for one panel, minimum cooling for a 10-server rack by TDP, and Carnot efficiency at Atlanta ambient (use Kelvin).', 'Show Kelvin for Carnot — mixing Celsius and Kelvin produces impossible efficiencies.'),
(50, 17, 2, 'Section 3.2 & The Refrigeration Cycle', 'videos/energy/wk3_sec32.mp4', 'Refrigerant phase change; evaporation, compression, condensation, expansion; coefficient of performance (COP).', 'Draw and label the four refrigeration cycle stages; annotate where heat is absorbed and rejected.', 'DX CRAC units in Week 4 are this cycle in a box — understand the cycle before sizing equipment.'),
(51, 17, 3, 'Section 3.3 & Data Center Heat Management', 'videos/energy/wk3_sec33.mp4', 'CPU/GPU as primary heat sources; heatsinks; thermal paste; fans and front-to-back airflow; vapor chambers; floor grilles; hot and cold aisles.', 'Upload a server airflow diagram: intake/exhaust direction, heatsink placement, and how rack placement supports hot/cold aisle containment.', 'Server-level cooling connects chip TDP to facility aisle design — document both scales.'),
(52, 18, 1, 'Section 4.1 & Direct Cooling vs. Chilled Water Cooling', 'videos/energy/wk4_sec41.mp4', 'DX self-contained units vs central chiller plants; precision AC vs consumer AC; cooling capacity vs power draw; COP; choosing DX vs chilled water by scale.', 'Upload a one-page recommendation: DX vs chilled water for the cohort pod — cite scale, complexity, and Atlanta climate.', 'Cooling capacity (kW removed) is not the same as electrical draw — read spec sheets carefully.'),
(53, 18, 2, 'Section 4.2 & Water Consumption and Closed Loop Cooling', 'videos/energy/wk4_sec42.mp4', 'WUE; open vs closed loop cooling; evaporative cooling and Atlanta humidity; water consumption at scale; closed loop as community accountability.', 'Compare monthly water use: open evaporative tower vs closed-loop system for a given IT load — one-page memo with WUE estimates.', 'Water is an environmental justice metric — Atlanta humidity limits evaporative effectiveness.'),
(54, 18, 3, 'Section 4.3 & Heat Recovery Systems', 'videos/energy/wk4_sec43.mp4', 'Heat recovery vs rejection; Organic Rankine Cycle; ORC turbine recovery; heat recovery doors; Carnot limits (~6–11% at DC temps); closed-loop water savings.', 'Upload a half-page recommendation: ORC vs heat recovery door vs reject-only for cohort scale — cite Carnot ceiling and complexity.', 'Heat recovery turns waste into an asset but never eliminates primary cooling — size both systems.'),
(55, 19, 1, 'Section 5.1 & General Power Systems', 'videos/energy/wk5_sec51.mp4', 'Power vs energy (W vs Wh); transformers and batteries; fossil generation; renewables and grid conversion; the duck curve.', 'Write a half-page explaining how a 250 W server running 24 hours maps to kWh consumed and why that matters for billing.', 'Power is instantaneous; energy is accumulated — both appear on utility bills differently.'),
(56, 19, 2, 'Section 5.2 & Energy and Electricity Pricing', 'videos/energy/wk5_sec52.mp4', 'Wholesale vs retail pricing; merit order; time-of-use rates; demand charges; Georgia Power CARES; levelized cost of energy (LCOE).', 'Upload a monthly cost projection comparing peak vs off-peak scheduling for a fixed IT load; note demand charge impact.', 'Demand charges punish brief spikes — load scheduling is an engineering and economic decision.'),
(57, 19, 3, 'Section 5.3 & Power Delivery Systems for Data Centers', 'videos/energy/wk5_sec53.mp4', 'Utility to PDU power chain; UPS ride-through; redundant PDUs; ATS source switching; generator backup; PUE and Carnot; on-site solar and battery storage.', 'Upload a one-line diagram from utility to rack PDU: UPS, ATS, generator, and solar — mark N+1 components and estimated PUE.', 'Redundancy is expensive — justify N+1 vs 2N for the 10-server cohort scope.'),
(58, 20, 1, 'Section 6.1 & Sensors, Meters, and Data Protocols', 'videos/energy/wk6_sec11.mp4', 'Sensor fundamentals; analog vs digital sensors; current/voltage sensors; smart PDU metering (SNMP/Modbus); Python variables and I/O.', 'Write a Python script that reads one simulated sensor value (temperature or power) and prints it in a labeled format.', 'This is the first step toward the energy dashboard — one clean reading before building the pipeline.'),
(59, 20, 2, 'Section 6.2 & Data Collection and Logging', 'videos/energy/wk6_sec12.mp4', 'Polling loops; timestamps; CSV file I/O; calculating live PUE and WUE from logged readings.', 'Expand your script into a loop that polls a simulated sensor every few seconds, logs timestamped readings to CSV, and prints a running PUE.', 'Persistent logs turn formulas into operational data — the same pattern Splunk uses at facility scale.'),
(60, 20, 3, 'Section 6.3 & Visualization and the Dashboard', 'videos/energy/wk6_sec13.mp4', 'Reading CSV back into memory; basic charting; Flask JSON routes; Chart.js live graphs in the browser.', 'Connect your logging pipeline to Flask and build a browser dashboard showing temperature, power draw, and PUE as live-updating charts.', 'Capstone: raw sensor data to a usable monitoring tool — the energy counterpart to the orchestration software dashboard.');

INSERT INTO `assignment` (`assignmentid`, `videoid`, `studentid`, `miniokey`, `status`, `feedback`, `submitted_at`) VALUES
(1, 3, 1, 'assignments/orchestration/james_wk1_calculator.cpp', 'submitted', NULL, '2026-01-12 13:22:00'),
(2, 4, 1, 'assignments/orchestration/james_wk2_hangman.cpp', 'satisfactory', 'Monolithic Hangman compiles and runs. Ready to refactor.', '2026-01-13 13:29:00'),
(3, 2, 2, 'assignments/orchestration/keisha_wk1_calculator.cpp', 'satisfactory', 'Basic calculator with all four operations works.', '2026-01-13 14:22:00'),
(4, 7, 2, 'assignments/orchestration/keisha_wk3_terminal_sim.cpp', 'satisfactory', 'Tree simulator handles cd and mkdir correctly.', '2026-01-15 14:36:00'),
(5, 30, 3, 'assignments/cloud/david_wk2_ordering.py', 'satisfactory', 'Customer, ServiceProvider, Inventory, and Order classes all instantiate correctly.', '2026-01-10 15:29:00'),
(6, 38, 3, 'assignments/cloud/david_wk5_frontend.html', 'unsatisfactory', 'Order history renders but place-order button missing event listener & fix handler.', '2026-01-11 15:36:00'),
(7, 30, 4, 'assignments/cloud/angela_wk2_ordering.py', 'satisfactory', 'Order histories print correctly from customer and vendor perspectives.', '2026-01-10 16:22:00'),
(8, 35, 4, 'assignments/cloud/angela_wk4_reviews.zip', 'unsatisfactory', 'Reviews INSERT works but SELECT missing ORDER BY timestamp.', '2026-01-11 16:29:00'),
(9, 43, 5, 'assignments/energy/terrence_wk1_circuits.pdf', 'unsatisfactory', 'Missing heat dissipation on one branch & show P = IV for each resistor.', '2026-01-11 17:22:00'),
(10, 49, 5, 'assignments/energy/terrence_wk3_thermal.pdf', 'submitted', NULL, '2026-01-13 17:36:00'),
(11, 48, 6, 'assignments/energy/michelle_wk2_spineleaf.pdf', 'submitted', NULL, '2026-01-13 10:29:00'),
(12, 52, 6, 'assignments/energy/michelle_wk4_cooling_memo.pdf', 'satisfactory', 'Strong DX vs chilled-water comparison for Atlanta climate.', '2026-01-14 10:36:00'),
(13, 4, 7, 'assignments/orchestration/brian_wk2_hangman.cpp', 'satisfactory', 'Raw Hangman runs & ready for function refactor.', '2026-01-11 13:29:00'),
(14, 7, 7, 'assignments/orchestration/brian_wk3_terminal_sim.cpp', 'unsatisfactory', 'touch command not implemented & add before resubmit.', '2026-01-12 13:36:00'),
(15, 2, 8, 'assignments/orchestration/renee_wk1_calculator.cpp', 'satisfactory', 'Basic calculator compile screenshot accepted.', '2026-01-11 14:22:00'),
(16, 5, 8, 'assignments/orchestration/renee_wk2_tictactoe.cpp', 'unsatisfactory', 'Infinite loop on invalid input & add input validation.', '2026-01-12 14:29:00'),
(17, 30, 9, 'assignments/cloud/carlos_wk2_ordering.py', 'unsatisfactory', 'Order class missing status field.', '2026-01-12 15:22:00'),
(18, 33, 9, 'assignments/cloud/carlos_wk3_rag_chatbot.zip', 'submitted', NULL, '2026-01-14 15:36:00'),
(19, 38, 10, 'assignments/cloud/nicole_wk5_frontend.zip', 'submitted', NULL, '2026-01-14 16:29:00'),
(20, 41, 10, 'assignments/cloud/nicole_wk6_azure_deploy.pdf', 'satisfactory', 'Azure Container Apps URL live; Dockerfile and README included.', '2026-01-15 16:36:00'),
(21, 44, 11, 'assignments/energy/kevin_wk1_breadboard.pdf', 'submitted', NULL, '2026-01-09 17:22:00'),
(22, 57, 11, 'assignments/energy/kevin_wk5_power_chain.pdf', 'satisfactory', 'N+1 diagram shows correct UPS ride-through path.', '2026-01-10 17:29:00'),
(23, 48, 12, 'assignments/energy/jasmine_wk2_spineleaf.pdf', 'satisfactory', 'Clear rack elevation with PDU placement.', '2026-01-10 10:22:00'),
(24, 60, 12, 'assignments/energy/jasmine_wk6_dashboard.zip', 'satisfactory', 'Flask dashboard renders live PUE chart from CSV log.', '2026-01-12 10:36:00');

INSERT INTO `channel` (`channelid`, `cohortid`, `type`, `name`) VALUES
(1, 1, 'general', 'General'),
(2, 1, 'division', 'Data Center Orchestration'),
(3, 1, 'division', 'Cloud Architect'),
(4, 1, 'division', 'Electrical Engineering'),
(5, 1, 'direct', NULL),
(6, 1, 'direct', NULL),
(7, 2, 'general', 'General'),
(8, 2, 'division', 'Data Center Orchestration'),
(9, 2, 'division', 'Cloud Architect'),
(10, 2, 'division', 'Electrical Engineering'),
(11, 2, 'direct', NULL),
(12, 2, 'direct', NULL);

INSERT INTO `channel_member` (`channelid`, `member_type`, `member_id`) VALUES
(1, 'student', 1),
(1, 'student', 2),
(1, 'student', 3),
(1, 'student', 4),
(1, 'student', 5),
(1, 'student', 6),
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
(1, 1, 'leader', 1, 'Welcome to Cohort 1! This program has three division tracks & Data Center Orchestration, Cloud Architect, and Electrical Engineering. General channel is for cross-track announcements.', '2026-01-06 09:00:00'),
(2, 1, 'admin', 1, 'Hi everyone & Sandra from platform ops. I drop org-wide updates here when we have community-cloud milestones.', '2026-01-06 09:15:00'),
(3, 1, 'student', 3, 'Cloud track checking in & finished my IaaS/PaaS/SaaS cloud audit for three tutoring apps. Feedback welcome in division channel.', '2026-01-06 14:22:00'),
(4, 1, 'leader', 1, 'Nice start David. Remember Week 1 Cloud goal: classify who manages what in the stack before you write backend code.', '2026-01-06 14:45:00'),
(5, 1, 'student', 1, 'Orchestration & anyone else stuck on the raw Hangman loop? My lives counter decrements twice sometimes.', '2026-01-07 11:03:00'),
(6, 4, 'student', 5, 'Electrical Engineering track & CRAC vs CRAH video finally clicked when Patricia mapped it to our Atlanta humidity.', '2026-01-15 13:40:00'),
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
(17, 7, 'student', 11, 'Electrical Engineering track & when do we walk the actual cohort lab space? Need to validate aisle layout.', '2026-01-09 15:00:00'),
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