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
DROP TABLE IF EXISTS `admin`;
DROP TABLE IF EXISTS `Week`;
DROP TABLE IF EXISTS `Course`;
DROP TABLE IF EXISTS `cohort`;

-- ============================================================
-- AARI Educational Suite & Data Center Course Schema
-- Asynchronous, LinkedIn-Learning-style cohort program with four
-- division-tracks (courses), weekly video lessons, graded assignments,
-- cohort chat (general/division/direct), progress tracking, and roster bios.
-- Notes:
--   * Password columns store bcrypt hashes (strings), NEVER plaintext.
--   * A student's courseid IS their division assignment.
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

CREATE TABLE `admin` (
    `adminid`  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `fname`    VARCHAR(255) NOT NULL,
    `lname`    VARCHAR(255) NOT NULL,
    `email`    VARCHAR(255) NOT NULL,
    `password` VARCHAR(255) NOT NULL,  -- bcrypt hash
    `cohortid` BIGINT UNSIGNED NOT NULL,   -- cohort this admin manages
    UNIQUE KEY `admin_email_unique` (`email`),
    CONSTRAINT `admin_cohortid_fk` FOREIGN KEY (`cohortid`) REFERENCES `cohort` (`cohortid`)
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
    `member_type` ENUM('student','admin') NOT NULL,
    `member_id`   BIGINT UNSIGNED NOT NULL,  -- studentid or adminid per member_type; validated in app code
    PRIMARY KEY (`channelid`, `member_type`, `member_id`),
    CONSTRAINT `cm_channel_fk` FOREIGN KEY (`channelid`) REFERENCES `channel` (`channelid`)
);

CREATE TABLE `messages` (
    `messagesid`  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `channelid`   BIGINT UNSIGNED NOT NULL,
    `sender_type` ENUM('student','admin') NOT NULL,
    `sender_id`   BIGINT UNSIGNED NOT NULL,  -- studentid or adminid per sender_type; validated in app code
    `content`     TEXT NOT NULL,
    `sendtime`    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX `messages_channelid_index` (`channelid`),
    CONSTRAINT `messages_channelid_fk` FOREIGN KEY (`channelid`) REFERENCES `channel` (`channelid`)
);


-- ============================================================
-- Seed data (local development)
-- Curriculum: Network Security, Data Center Orchestration,
-- Cloud Architect, Energy (6 weeks × 3 sessions each)
-- Use: python make_test_login.py --suite dc --reset-all
-- ============================================================

SET @pw = '123123';

INSERT INTO `Course` (`courseid`, `name`, `description`, `teacher`) VALUES
(1, 'Network Security', 'Own all networking and security decisions for the data center - network architecture, access control, cloud security, physical security, and cyber policy. Six weeks, three two-hour sections per week. You create the conditions for the rest of the cohort to build without distraction.', 'Dr. Samuel Okonkwo'),
(2, 'Data Center Orchestration', 'Own compute, networking, storage, and virtualization decisions for the data center. From C++ and low-level computing through Proxmox, Splunk, and a full-stack monitoring dashboard - the engineering backbone that keeps infrastructure visible and fault-tolerant.', 'Miguel Santos'),
(3, 'Cloud Architect', 'Develop and maintain the Community Cloud Platform - JavaScript and web fundamentals, Flask and MySQL, AI and LLM chatbots, Docker deployment, and the community-cloud business model. Build software services local businesses can actually use.', 'Dr. Lisa Zhang'),
(4, 'Electrical Engineering', 'Power delivery, cooling infrastructure, and renewable energy design for the community cloud data center. Six weeks covering electrical fundamentals through solar integration, PUE, and the clean data center capstone - the bridge between software and physical infrastructure.', 'Patricia Hammond');

INSERT INTO `cohort` (`cohortid`, `region`, `name`) VALUES
(1, 'Atlanta', 'Cohort 1'),
(2, 'Atlanta', 'Cohort 2');

INSERT INTO `admin` (`adminid`, `fname`, `lname`, `email`, `password`, `cohortid`) VALUES
(1, 'Denise',  'Parker', 'denise.parker@aari.org',  @pw, 1),
(2, 'Robert',  'Kim',    'robert.kim@aari.org',     @pw, 2),
(3, 'Sandra',  'Ellis',  'sandra.ellis@aari.org',   @pw, 2);

INSERT INTO `student` (`studentid`, `fname`, `lname`, `email`, `password`, `courseid`, `cohortid`, `bio`) VALUES
(1, 'Marcus', 'Allen', 'marcus.allen@aari.org', @pw, 1, 1, 'Network Security track - focused on spine-leaf design for the cohort build.'),
(2, 'Tanya', 'Brooks', 'tanya.brooks@aari.org', @pw, 1, 1, 'Studying iptables and NFS hardening before our pod goes live.'),
(3, 'James', 'Porter', 'james.porter@aari.org', @pw, 2, 1, 'Orchestration software specialist - building the Splunk monitoring dashboard.'),
(4, 'Keisha', 'Williams', 'keisha.williams@aari.org', @pw, 2, 1, 'Porting C++ Hangman to JavaScript this week.'),
(5, 'David', 'Nguyen', 'david.nguyen@aari.org', @pw, 3, 1, 'Cloud Architect - wireframing a tutoring business community-cloud site.'),
(6, 'Angela', 'Martinez', 'angela.martinez@aari.org', @pw, 3, 1, 'Working on Flask + MySQL reviews table for my service-ordering app.'),
(7, 'Terrence', 'Jackson', 'terrence.jackson@aari.org', @pw, 4, 1, 'Electrical Engineering track - comparing DX vs chilled-water for our Atlanta facility.'),
(8, 'Michelle', 'Chen', 'michelle.chen@aari.org', @pw, 4, 1, 'Drafting hot/cold aisle layout and heat recovery plan.'),
(9, 'Andre', 'Simmons', 'andre.simmons@aari.org', @pw, 1, 2, 'Subnetting practice for the secure pod capstone.'),
(10, 'Latoya', 'Green', 'latoya.green@aari.org', @pw, 1, 2, 'Network Security - spine-leaf diagram in progress.'),
(11, 'Brian', 'O''Connor', 'brian.oconnor@aari.org', @pw, 2, 2, 'RAID lab in VirtualBox - orchestration track.'),
(12, 'Renee', 'Foster', 'renee.foster@aari.org', @pw, 2, 2, 'Express dashboard connecting to /servers API.'),
(13, 'Carlos', 'Rivera', 'carlos.rivera@aari.org', @pw, 3, 2, 'RAG chatbot for auto-repair industry on my community-cloud site.'),
(14, 'Nicole', 'Adams', 'nicole.adams@aari.org', @pw, 3, 2, 'Deploying Flask app to Railway for Week 6 cloud migration.'),
(15, 'Kevin', 'Patel', 'kevin.patel@aari.org', @pw, 4, 2, 'Electrical Engineering - power redundancy analysis for cohort pod, N+1 calculations.'),
(16, 'Jasmine', 'Wright', 'jasmine.wright@aari.org', @pw, 4, 2, 'Clean data center capstone - solar sizing and 50/40/10 energy model.');

INSERT INTO `Week` (`weekid`, `courseid`, `subject`, `num`, `description`) VALUES
(1, 1, 'Networking Fundamentals', 1, 'Network types, OSI/TCP-IP, addressing, DNS, switches, routers, and wireless - the vocabulary every security decision builds on.'),
(2, 1, 'Data Center Networking', 2, 'Three-tier vs spine-leaf, traffic directionality, STP, structured cabling, and wireless management access in the facility.'),
(3, 1, 'Cybersecurity Foundations', 3, 'CIA triad, threat modeling, common attacks, cryptography, TLS, and the security mindset for every layer.'),
(4, 1, 'Data Center Security', 4, 'Physical access control, firewalls, segmentation, IAM, SIEM, and incident response playbooks.'),
(5, 1, 'Cloud Security', 5, 'Shared responsibility, VPC security, secrets management, compliance frameworks, and DevSecOps in the pipeline.'),
(6, 1, 'Cyber Policy for the Community Cloud', 6, 'Security policy, member-business access rules, and the collaborative capstone security addendum with the cloud cohort.'),
(7, 2, 'What is Computer Science', 1, 'Hardware, software, programming, and networking - the foundations both orchestration specialists share before branching deep.'),
(8, 2, 'Abstraction: Loops, Functions - Binary', 2, 'Loops, functions, arrays, and binary/bitwise operations including network bit masking in C++.'),
(9, 2, 'Low Level Computing', 3, 'C++ classes, pointers, memory, linked lists, trees, and a simplified 8-bit MIPS CPU simulator.'),
(10, 2, 'Data Centers 101', 4, 'Compute and RAID configuration, data-center networking in VirtualBox, and Proxmox virtualization with Splunk monitoring.'),
(11, 2, 'Web Development for Monitoring', 5, 'Migrate C++ logic to JavaScript; build and style a server monitoring dashboard with HTML and CSS.'),
(12, 2, 'Full Stack Infrastructure Monitoring', 6, 'Express APIs, MySQL CRUD for server logs, and a normalized schema linking servers, VMs, and log history.'),
(13, 3, 'How Software Works: Your First Program', 1, 'Software vs hardware, how websites work, JavaScript basics, variables, and your first calculator programs.'),
(14, 3, 'Programming Fundamentals II', 2, 'Loops, functions, Hangman refactor, and object-oriented modeling with Service, Customer, and Order classes.'),
(15, 3, 'From Code to Web Page: HTML, CSS - APIs', 3, 'DOM manipulation, styling to match your wireframe, JSON, fetch(), and live industry news on the home page.'),
(16, 3, 'Server-Side and Databases', 4, 'Python and Flask routes, MySQL CRUD, reviews table, and a normalized customers/services/orders schema with JOINs.'),
(17, 3, 'Artificial Intelligence', 5, 'NumPy and data representation, neural networks in Colab, LLMs, RAG, and an Ollama-powered industry chatbot on your site.'),
(18, 3, 'Cloud Computing - Community Cloud', 6, 'DNS and local network access, Docker and cloud deployment, and the community-cloud business proposal capstone.'),
(19, 4, 'Electrical Fundamentals', 1, 'Charge, voltage, current, Ohm''s law, circuits, components, and AC power safety - quantitative foundations for every power decision.'),
(20, 4, 'Electronics and Digital Logic', 2, 'Semiconductors, logic gates, CMOS, from gates to CPU, signal integrity, and power delivery at the board level.'),
(21, 4, 'Thermodynamics and Refrigeration', 3, 'Heat transfer modes, refrigeration cycle, PUE, Carnot efficiency, and Atlanta climate as an engineering input.'),
(22, 4, 'Data Center Cooling Systems', 4, 'DX CRAC, chilled water and CRAHs, heat recovery and ORC, cold/hot aisle containment.'),
(23, 4, 'Power Infrastructure', 5, 'Utility feed, UPS, generators, PDUs, rack power density, redundancy, and DCIM monitoring.'),
(24, 4, 'Renewable Energy and Clean Data Center Design', 6, 'Solar PV, 50/40/10 energy model, environmental accountability, and the clean data center capstone.');

INSERT INTO `video` (`videoid`, `weekid`, `day`, `title`, `miniokey`, `script`, `instructions`, `reflection`) VALUES
(1, 1, 1, 'Section 1.1 & Network Scope and the OSI Model', 'videos/netsec/wk1_sec11.mp4', 'Network types (PAN through WAN); Wi-Fi vs cellular; VPN tunnels; OSI seven layers; TCP/IP four-layer model; TCP vs UDP', 'Complete the in-class OSI layer worksheet: for ping, curl, SSH, and HTTPS, note which OSI layer each primarily operates at.', 'This week establishes the language you will use for every network and security decision in the cohort build. Focus on layer boundaries - they are how you troubleshoot.'),
(2, 1, 2, 'Section 1.2 & Network Addressing', 'videos/netsec/wk1_sec12.mp4', 'MAC vs IP addresses; IPv4 vs IPv6; Network vs host portions and subnet masks; Private vs public IP; DHCP four-step process; Static vs dynamic IP; ARP and NAT', 'Upload a one-page diagram of your home or lab network showing one device path from application to physical layer, labeling MAC, private IP, public IP, and where NAT occurs.', 'Addressing is where abstract network design becomes concrete. Your diagram should show both local delivery (MAC/ARP) and internet-bound traffic (NAT).'),
(3, 1, 3, 'Section 1.3 & Network Services, Hardware, and Wireless', 'videos/netsec/wk1_sec13.mp4', 'DNS resolution hierarchy; HTTP vs HTTPS; QoS prioritization; Switches vs routers; Copper vs fiber cabling; Wi-Fi bands and WAP types', 'Run nslookup and curl -v against one HTTPS site; upload screenshots with DNS answer and TLS handshake notes.', 'DNS and TLS failures are among the first symptoms students see when security rules are wrong - learn to read these tools now.'),
(4, 2, 1, 'Section 2.1 & Data Center Network Architecture', 'videos/netsec/wk2_sec21.mp4', 'Layer 2 vs Layer 3 vs multilayer switches; Three-tier access/aggregation/core; Northbound, southbound, east-west traffic; Spine-leaf architecture; Load balancing; Nexus switches', 'Sketch a spine-leaf pod for six servers: label spine switches, leaf ToR switches, and mark one east-west and one northbound traffic path.', 'East-west dominates in modern data centers - your spine-leaf sketch should make two-hop paths obvious.'),
(5, 2, 2, 'Section 2.2 & Loop Prevention and Physical Infrastructure', 'videos/netsec/wk2_sec22.mp4', 'Switching loops and broadcast storms; Spanning Tree Protocol; Network racks vs compute racks; Patch panels; Structured cabling and cable management', 'Upload a rack elevation showing network rack separated from compute, with patch panel, switch, and labeled cable paths.', 'Clean physical infrastructure is a security control - tangled cabling hides unauthorized taps and slows incident response.'),
(6, 2, 3, 'Section 2.3 & Data Center Wireless and Remote Access', 'videos/netsec/wk2_sec23.mp4', 'Wireless for OOB management and IoT; Out-of-band management networks; VLAN segmentation; SSID isolation; WPA3 and certificate-based auth', 'Draft a VLAN plan with at least three segments: production, management, and storage. Upload a table listing SSID/VLAN, purpose, and allowed devices.', 'Management networks must never share a flat LAN with production - your VLAN plan is the blueprint for that separation.'),
(7, 3, 1, 'Section 3.1 & The Security Mindset and Core Concepts', 'videos/netsec/wk3_sec31.mp4', 'CIA triad; Threat vs vulnerability vs risk; Attack surface reduction; Defense in depth; Least privilege; Zero trust', 'Pick one cohort service (web app, NFS share, or SSH admin) and write a half-page threat model: assets, threats, vulnerabilities, and one control per CIA pillar.', 'Threat modeling is not paperwork - it is how you decide which controls earn their complexity in a small data center.'),
(8, 3, 2, 'Section 3.2 & Common Attacks and How They Work', 'videos/netsec/wk3_sec32.mp4', 'Social engineering and phishing; Man-in-the-middle; DoS and DDoS; SQL injection; Privilege escalation; Lateral movement', 'In a lab VM, demonstrate one blocked and one allowed iptables rule for SSH; upload rule list and screenshot of each connection attempt.', 'Hands-on firewall work connects abstract attack types to the rules you will live with during the build season.'),
(9, 3, 3, 'Section 3.3 & Cryptography and Secure Communication', 'videos/netsec/wk3_sec33.mp4', 'Symmetric vs asymmetric encryption; TLS handshake; Hashing and password storage; Digital certificates; PKI and certificate authorities', 'Use openssl to inspect a public HTTPS certificate chain; upload terminal output and note issuer, subject, and expiry.', 'Every HTTPS connection your community cloud serves depends on PKI - know how to verify certificates before you trust them.'),
(10, 4, 1, 'Section 4.1 & Physical Security and Access Control', 'videos/netsec/wk4_sec41.mp4', 'Physical security as first layer; Access zones and layered authentication; Mantraps and tailgating prevention; CCTV and audit logging; Rack-level security', 'Create a facilities access matrix: rows are zones (perimeter, floor, rack), columns are roles (technician, admin, visitor), cells describe required auth.', 'If an attacker can walk to a server, network controls matter less - physical zones are your outermost firewall.'),
(11, 4, 2, 'Section 4.2 & Network Security Controls', 'videos/netsec/wk4_sec42.mp4', 'Stateful vs stateless firewalls; IDS vs IPS; Network segmentation; DMZ design; Port security; Vulnerability scanning', 'Upload iptables or UFW rules for a three-tier pod: DMZ web server, internal app server, and NFS segment - default deny inbound on each.', 'Segmentation limits blast radius - your rules should make a DMZ compromise unable to reach storage directly.'),
(12, 4, 3, 'Section 4.3 & Identity, Monitoring, and Incident Response', 'videos/netsec/wk4_sec43.mp4', 'IAM and RBAC; Multi-factor authentication; SIEM log aggregation; Log integrity; Incident response phases; Backup and recovery testing', 'Write a one-page incident response outline for a suspected SSH brute-force: identify, contain, eradicate, recover, and lessons learned.', 'Playbooks beat improvisation - draft this before an incident, not during one.'),
(13, 5, 1, 'Section 5.1 & Cloud Security Fundamentals', 'videos/netsec/wk5_sec51.mp4', 'Shared responsibility model; Cloud attack surface (IAM, buckets, APIs); Secrets management; Encryption at rest and in transit', 'Audit a sample Terraform or cloud console screenshot (provided in class): list three misconfigurations and the least-privilege fix for each.', 'Misconfigured IAM is the leading cloud breach cause - practice spotting it before you deploy the community cloud.'),
(14, 5, 2, 'Section 5.2 & Cloud Network Security', 'videos/netsec/wk5_sec52.mp4', 'Virtual private clouds; Security groups vs NACLs; Private endpoints; DDoS protection tiers; Cloud WAF', 'Diagram a VPC with public subnet (WAF + load balancer), private app subnet, and private data subnet; label security group rules between tiers.', 'Cloud networking mirrors on-prem segmentation - your VPC diagram is the security engineer''s contribution to the architecture review.'),
(15, 5, 3, 'Section 5.3 & Compliance, Auditing, and DevSecOps', 'videos/netsec/wk5_sec53.mp4', 'SOC 2, ISO 27001, NIST CSF overview; Cloud audit logging (CloudTrail, etc.); Infrastructure-as-code security scanning; DevSecOps pipeline checks; Penetration testing rules', 'List five DevSecOps checks you would add to the cohort CI pipeline (dependency scan, secret scan, etc.) with one sentence on what each catches.', 'Shift-left security means catching misconfigurations in code review, not after a member business is live on the platform.'),
(16, 6, 1, 'Section 6.1 & Security Policy Foundations', 'videos/netsec/wk6_sec61.mp4', 'What a security policy is; Acceptable use policy; Data classification; Retention and deletion; Incident disclosure obligations', 'Draft a data classification table (public, internal, confidential, restricted) with one example data type per level from a local business on the platform.', 'Policy turns ethics into enforceable rules - your classification table feeds directly into the Week 6 capstone addendum.'),
(17, 6, 2, 'Section 6.2 & Access Policy for Local Business Members', 'videos/netsec/wk6_sec62.mp4', 'RBAC for member businesses; Onboarding and offboarding procedures; Password and MFA policy; Third-party vendor access; User awareness training', 'Write onboarding and offboarding checklists for a new salon joining the community cloud - every account, key, and integration that must be created or revoked.', 'Incomplete offboarding is a common breach source - treat departure as a security event, not an HR afterthought.'),
(18, 6, 3, 'Section 6.3 & Collaborative Capstone: Security Addendum', 'videos/netsec/wk6_sec63.mp4', 'Joint session with cloud cohort; Review cloud business proposals; Security addendum: access control, network controls, data handling, incident response', 'Upload the security addendum attached to one cloud cohort business proposal: access control design, network controls, data/retention policy, and incident response outline. Present jointly with your cloud partner.', 'This capstone mirrors real product and security collaboration. Your addendum should make the cloud student''s proposal deployable without hand-waving security.'),
(19, 7, 1, 'Session 1.1 & Hardware, Software, Programming & Networking', 'videos/orchestration/wk1_vid1.mp4', 'CPU, RAM, firmware, OS, apps, and networking as data-center foundations.', 'Install VS Code for C++; run Hello World before project.', 'Today''s session sets up the lab work for this week. Take notes on the demo - you''ll reference them in the project.'),
(20, 7, 2, 'Project & Terminal Basics & VS Code Setup', 'videos/orchestration/wk1_vid2.mp4', 'Navigate dirs, create files, compile/run Hello World in C++.', 'Upload terminal screenshot of successful compile and run.', 'This project builds directly on this week''s sessions. Upload terminal screenshot of successful compile and run - focus on clarity and completeness, not speed.'),
(21, 7, 3, 'Review & CS Foundations Q&A', 'videos/orchestration/wk1_vid3.mp4', 'Hardware vs software and terminal commands you will reuse all semester.', 'No upload required.', 'Use today''s review to connect this lesson to the hands-on work ahead. Come with one question you still have.'),
(22, 8, 1, 'Session 2.1 & Loops and Arrays', 'videos/orchestration/wk2_vid1.mp4', 'while/for loops, arrays, iteration for infrastructure software.', 'Watch before Hangman lab.', 'Today''s session sets up the lab work for this week. Take notes on the demo - you''ll reference them in the project.'),
(23, 8, 2, 'Project & Hangman (Raw Version)', 'videos/orchestration/wk2_vid2.mp4', 'Monolithic C++ Hangman: hardcoded word, guess loop, lives.', 'Upload single-block .cpp.', 'This project builds directly on this week''s sessions. Upload single-block - focus on clarity and completeness, not speed.'),
(24, 8, 3, 'Session 2.3 & Binary & Bit Masking', 'videos/orchestration/wk2_vid3.mp4', 'Binary, hex, truth tables, bitwise ops for network addresses.', 'Notes on AND/OR for subnets.', 'Today''s session sets up the lab work for this week. Take notes on the demo - you''ll reference them in the project.'),
(25, 9, 1, 'Session 3.1 & Objects: Classes in C++', 'videos/orchestration/wk3_vid1.mp4', 'Members, methods, constructors, encapsulation, getters/setters.', 'Review Hangman - larger systems use OOP.', 'Today''s session sets up the lab work for this week. Take notes on the demo - you''ll reference them in the project.'),
(26, 9, 2, 'Project & Terminal Simulator (Tree Structure)', 'videos/orchestration/wk3_vid2.mp4', 'Simulate ls, cd, mkdir, touch with directory tree and pointers.', 'Upload .cpp and demo of four+ commands.', 'This project builds directly on this week''s sessions. Upload - focus on clarity and completeness, not speed.'),
(27, 9, 3, 'Session 3.3 & Instruction Set Architecture', 'videos/orchestration/wk3_vid3.mp4', 'CPU pipeline, registers, GPUs for AI workloads.', 'Prep for Week 4 compute.', 'Today''s session sets up the lab work for this week. Take notes on the demo - you''ll reference them in the project.'),
(28, 10, 1, 'Session 4.1 & Compute, RAID & Virtualization Overview', 'videos/orchestration/wk4_vid1.mp4', 'Server types, ECC, RAID, Proxmox, Splunk, fault tolerance.', 'Review RAID levels before lab.', 'Today''s session sets up the lab work for this week. Take notes on the demo - you''ll reference them in the project.'),
(29, 10, 2, 'Project & RAID Configuration in VirtualBox', 'videos/orchestration/wk4_vid2.mp4', 'mdadm RAID; verify after simulated disk failure.', 'Upload mdadm output before/after failure.', 'This project builds directly on this week''s sessions. Upload mdadm output before/after failure - focus on clarity and completeness, not speed.'),
(30, 10, 3, 'Project & NFS and Firewall in VirtualBox', 'videos/orchestration/wk4_vid3.mp4', 'NFS share between two VMs with iptables permitting only NFS traffic.', 'Upload exports, mount proof, and firewall rules.', 'This project builds directly on this week''s sessions. Upload exports, mount proof, and firewall rules - focus on clarity and completeness, not speed.'),
(31, 11, 1, 'Session 5.1 & Migrating C++ to JavaScript', 'videos/orchestration/wk5_vid1.mp4', 'Map variables, functions, control flow, JSON from C++ to JS.', 'Choose calculator or Hangman to port.', 'Today''s session sets up the lab work for this week. Take notes on the demo - you''ll reference them in the project.'),
(32, 11, 2, 'Project & C++ to JavaScript Translation', 'videos/orchestration/wk5_vid2.mp4', 'Rewrite calculator or Hangman in JS; run in browser console.', 'Upload .js and console screenshot.', 'This project builds directly on this week''s sessions. Upload - focus on clarity and completeness, not speed.'),
(33, 11, 3, 'Session 5.2 & HTML & the DOM', 'videos/orchestration/wk5_vid3.mp4', 'DOM tree, tags, getElementById, events, linking scripts.', 'Before dashboard shell project.', 'Today''s session sets up the lab work for this week. Take notes on the demo - you''ll reference them in the project.'),
(34, 12, 1, 'Session 6.1 & Express Server Development', 'videos/orchestration/wk6_vid1.mp4', 'APIs, Express routes, fetch() from dashboard front end.', 'Have dashboard shell ready.', 'Today''s session sets up the lab work for this week. Take notes on the demo - you''ll reference them in the project.'),
(35, 12, 2, 'Project & Connect Dashboard to Express', 'videos/orchestration/wk6_vid2.mp4', '/servers and /vms JSON routes feeding the monitoring UI.', 'Upload API screenshot and route code.', 'This project builds directly on this week''s sessions. Upload API screenshot and route code - focus on clarity and completeness, not speed.'),
(36, 12, 3, 'Project & Full Dashboard Schema with JOINs', 'videos/orchestration/wk6_vid3.mp4', 'servers, VMs, logs tables; JOIN for VM list and log history.', 'Upload ERD and JOIN query output.', 'This project builds directly on this week''s sessions. Upload ERD and JOIN query output - focus on clarity and completeness, not speed.'),
(37, 13, 1, 'Session 1.1 & How Software Thinks: From Idea to Interface', 'videos/cloud/wk1_vid1.mp4', 'Software vs hardware, URL cycle, website anatomy, design thinking, DevTools.', 'Pick local business industry for wireframe.', 'Today''s session sets up the lab work for this week. Take notes on the demo - you''ll reference them in the project.'),
(38, 13, 2, 'Project & Website Blueprint Wireframe', 'videos/cloud/wk1_vid2.mp4', '3 - 5 pages: home, services, booking, reviews, contact - label actions.', 'Upload wireframe with all pages labeled.', 'This project builds directly on this week''s sessions. Upload wireframe with all pages labeled - focus on clarity and completeness, not speed.'),
(39, 13, 3, 'Session 1.3 & Logic and Control Flow', 'videos/cloud/wk1_vid3.mp4', 'Booleans, if/else, switch; calculator with menu and divide-by-zero guard.', 'Build menu calculator after watching.', 'Today''s session sets up the lab work for this week. Take notes on the demo - you''ll reference them in the project.'),
(40, 14, 1, 'Session 2.1 & Loops and Arrays in JavaScript', 'videos/cloud/wk2_vid1.mp4', 'while/for, arrays, .push(), iteration.', 'Before Hangman refactor.', 'Today''s session sets up the lab work for this week. Take notes on the demo - you''ll reference them in the project.'),
(41, 14, 2, 'Project & Hangman Refactored (JavaScript)', 'videos/cloud/wk2_vid2.mp4', 'chooseWord(), displayWord(), checkGuess(), updateLives(), isGameOver().', 'Upload modular .js.', 'This project builds directly on this week''s sessions. Upload modular - focus on clarity and completeness, not speed.'),
(42, 14, 3, 'Session 2.3 & Object-Oriented Programming', 'videos/cloud/wk2_vid3.mp4', 'class, constructor, this, encapsulation, multiple instances.', 'Prep Service/Customer/Order classes.', 'Today''s session sets up the lab work for this week. Take notes on the demo - you''ll reference them in the project.'),
(43, 15, 1, 'Session 3.1 & HTML as Objects', 'videos/cloud/wk3_vid1.mp4', 'DOM, tags, getElementById, innerHTML, events.', 'Connect JS classes to HTML services page.', 'Today''s session sets up the lab work for this week. Take notes on the demo - you''ll reference them in the project.'),
(44, 15, 2, 'Project & Objects Meet the Browser', 'videos/cloud/wk3_vid2.mp4', 'Render Service cards; click logs Order to console.', 'Upload HTML/JS and services page screenshot.', 'This project builds directly on this week''s sessions. Upload HTML/JS and services page screenshot - focus on clarity and completeness, not speed.'),
(45, 15, 3, 'Session 3.3 & JSON and APIs', 'videos/cloud/wk3_vid3.mp4', 'JSON.stringify/parse, fetch(), CORS conceptually.', 'Prep live news on home page.', 'Today''s session sets up the lab work for this week. Take notes on the demo - you''ll reference them in the project.'),
(46, 16, 1, 'Session 4.1 & Python and Flask', 'videos/cloud/wk4_vid1.mp4', 'Server rationale, Python syntax map, Flask routes, GET/POST, jsonify.', 'Set up Flask venv.', 'Today''s session sets up the lab work for this week. Take notes on the demo - you''ll reference them in the project.'),
(47, 16, 2, 'Project & Connect Front End to Flask', 'videos/cloud/wk4_vid2.mp4', '/services JSON and /order POST; fetch() hits local Flask.', 'Upload Flask snippet and front-end screenshot.', 'This project builds directly on this week''s sessions. Upload Flask snippet and front-end screenshot - focus on clarity and completeness, not speed.'),
(48, 16, 3, 'Session 4.3 & Relationships and Normalization', 'videos/cloud/wk4_vid3.mp4', 'PK/FK, junction tables, JOINs, 3NF schema.', 'Draw ERD before schema project.', 'Today''s session sets up the lab work for this week. Take notes on the demo - you''ll reference them in the project.'),
(49, 17, 1, 'Session 5.1 & Data Representation for AI', 'videos/cloud/wk5_vid1.mp4', 'NumPy, vectors, normalization, images as matrices, Pandas.', 'Open Colab notebook from resources.', 'Today''s session sets up the lab work for this week. Take notes on the demo - you''ll reference them in the project.'),
(50, 17, 2, 'Project & Image Classifier in Colab', 'videos/cloud/wk5_vid2.mp4', 'Pretrained classifier on industry images; vary inputs and confidence.', 'Upload Colab screenshot with 3+ predictions.', 'This project builds directly on this week''s sessions. Upload Colab screenshot with 3+ predictions - focus on clarity and completeness, not speed.'),
(51, 17, 3, 'Session 5.3 & LLMs, RAG & Ollama', 'videos/cloud/wk5_vid3.mp4', 'Tokenization, system prompts, RAG pipeline, local LLMs.', 'Gather industry markdown for knowledge base.', 'Today''s session sets up the lab work for this week. Take notes on the demo - you''ll reference them in the project.'),
(52, 18, 1, 'Session 6.1 & DNS and Networking', 'videos/cloud/wk6_vid1.mp4', 'IPs, ports, DNS chain, /etc/hosts, ping, nslookup, curl.', 'Configure local DNS before cloud deploy.', 'Today''s session sets up the lab work for this week. Take notes on the demo - you''ll reference them in the project.'),
(53, 18, 2, 'Project & Migrate to the Cloud', 'videos/cloud/wk6_vid2.mp4', 'Dockerfile, deploy to Railway/Render, cloud MySQL, hosted LLM API.', 'Upload public URL and Dockerfile.', 'This project builds directly on this week''s sessions. Upload public URL and Dockerfile - focus on clarity and completeness, not speed.'),
(54, 18, 3, 'Session 6.3 & Community Cloud Model', 'videos/cloud/wk6_vid3.mp4', 'Hyperscaler incentives, digital gravity, local ownership, nonprofit governance.', 'Draft proposal while watching.', 'Today''s session sets up the lab work for this week. Take notes on the demo - you''ll reference them in the project.'),
(55, 19, 1, 'Section 1.1 & Charge, Voltage, and Current', 'videos/energy/wk1_sec11.mp4', 'Electric charge; Voltage as potential difference; Current in amperes; Resistance and Ohm''s law; Power P = IV and heat generation', 'Upload worked solutions for the Week 1 circuit analysis set: voltage drops, branch currents, and heat dissipation for at least three circuits using V = IR and P = IV.', 'Every rack power budget you will calculate this semester starts with Ohm''s law and power - show your units on every step.'),
(56, 19, 2, 'Section 1.2 & Circuits and Components', 'videos/energy/wk1_sec12.mp4', 'Series vs parallel circuits; Capacitors and inductors; Diodes and AC-to-DC conversion; Transistors as switches; Breadboard measurement practice', 'Upload a photo of your breadboard circuit (LED, resistor, switch) plus multimeter readings at two points that verify your hand calculations.', 'If your measured values disagree with calculations by more than 10%, find the wiring or math error before moving on - that discipline matters at rack scale.'),
(57, 19, 3, 'Section 1.3 & AC Power and Electrical Safety', 'videos/energy/wk1_sec13.mp4', 'AC vs DC; 60 Hz frequency and RMS voltage; Three-phase power; Grounding and bonding; Electrical safety and lethal current', 'Complete the AC safety checklist quiz in class; upload signed acknowledgment and one paragraph on why three-phase matters for data center feeds.', 'High current kills - safety procedures on this floor are non-negotiable when we move to live PDU work later in the program.'),
(58, 20, 1, 'Section 2.1 & Semiconductors and Logic Gates', 'videos/energy/wk2_sec21.mp4', 'Semiconductors and doping; P-N junction; MOSFET switches; Logic gates (AND, OR, NOT, NAND); CMOS power efficiency', 'In the logic simulator, build a half adder and full adder; upload truth table screenshots and a brief note on where carry propagates.', 'Logic gates are how software meets silicon - this is the same abstraction your orchestration peers debug at a higher level.'),
(59, 20, 2, 'Section 2.2 & From Gates to Computing Hardware', 'videos/energy/wk2_sec22.mp4', 'Combinational vs sequential logic; Flip-flops and registers; Clock signal; ALU operations; Memory hierarchy; Why chips generate heat', 'Calculate total TDP for a 10-server rack given per-server TDP values from the spec sheet; show sum and note which component generates the most heat.', 'TDP drives cooling sizing - this calculation is the bridge between electronics lecture and Week 4 CRAC design.'),
(60, 20, 3, 'Section 2.3 & Signal Integrity and Power Delivery', 'videos/energy/wk2_sec23.mp4', 'Signal integrity at high speed; Impedance matching; VRM and power delivery network; Decoupling capacitors; Thermal interface materials; TDP as cooling design input', 'Sketch a simplified power path from PSU to CPU (PSU → VRM → decoupling caps → die → TIM → heatsink) and label where voltage is regulated vs where heat exits.', 'Power delivery and thermal paths are two sides of the same problem - every watt in becomes heat out.'),
(61, 21, 1, 'Section 3.1 & Heat and Energy Transfer', 'videos/energy/wk3_sec31.mp4', 'Thermal vs kinetic energy; Conduction, convection, radiation; First law: energy in equals heat out; Second law and refrigeration work; Conduction formula Q/t = kAΔT/d; Specific heat Q = mcΔT', 'Upload thermal calculation worksheet: wall heat loss for one panel, minimum cooling capacity for a 10-server rack, and Carnot efficiency at Atlanta ambient.', 'Show Kelvin for Carnot - a common mistake is mixing Celsius and Kelvin and getting impossible efficiencies.'),
(62, 21, 2, 'Section 3.2 & The Refrigeration Cycle', 'videos/energy/wk3_sec32.mp4', 'Refrigerant and phase change; Evaporation, compression, condensation, expansion; Coefficient of performance (COP)', 'Draw and label the four stages of the refrigeration cycle on a P-h or T-s style sketch; annotate where heat is absorbed and rejected.', 'DX CRAC units in Week 4 are this cycle in a box - if the cycle is fuzzy now, CRAC sizing will feel like magic later.'),
(63, 21, 3, 'Section 3.3 & PUE and Efficiency Metrics', 'videos/energy/wk3_sec33.mp4', 'Power Usage Effectiveness; Carnot efficiency limits; Ambient temperature impact; Humidity and evaporative cooling; Energy cost modeling', 'Given IT load and measured facility power, compute PUE; upload calculation and one sentence on what facility overhead contributes most in our cohort lab.', 'PUE is how you prove environmental claims with numbers - the capstone will ask for a target and how each system choice supports it.'),
(64, 22, 1, 'Section 4.1 & Direct Expansion Cooling', 'videos/energy/wk4_sec41.mp4', 'DX and CRAC airflow; Upflow vs downflow; Cold aisle / hot aisle containment; Floor grilles and airflow; DX limitations at scale', 'Upload a floor plan: rack rows in cold/hot aisle layout, CRAC placement, floor grilles at cold aisles, and total cooling capacity vs rack TDP.', 'Air mixing destroys cooling efficiency - containment on paper is cheaper than fighting hot spots on the floor.'),
(65, 22, 2, 'Section 4.2 & Chilled Water Cooling', 'videos/energy/wk4_sec42.mp4', 'Chiller plant and chilled water loop; CRAH vs CRAC; Condenser water and cooling towers; Wet tower water consumption; N+1 chiller redundancy', 'Size chilled water flow for a given heat load; compare monthly water use of wet tower vs closed-loop ORC approach in a one-page memo.', 'Water consumption is a sustainability metric, not just a utility bill - Atlanta humidity affects evaporative choices.'),
(66, 22, 3, 'Section 4.3 & Heat Recovery Systems', 'videos/energy/wk4_sec43.mp4', 'Heat recovery vs rejection; Organic Rankine Cycle (ORC); Heat recovery doors; Carnot limits on recovery; Water savings of closed-loop ORC', 'Upload a half-page recommendation: for our cohort scale, ORC vs heat recovery door vs reject-only - cite Carnot ceiling and complexity tradeoff.', 'Heat recovery turns waste into an asset but never eliminates the need for primary cooling - size both.'),
(67, 23, 1, 'Section 5.1 & Data Center Power Delivery', 'videos/energy/wk5_sec51.mp4', 'Utility feed and transformers; Switchgear; UPS systems; Generator backup; PDUs; N+1 vs 2N redundancy', 'Upload a one-line diagram from utility to rack PDU showing UPS, generator, and switchgear; mark N+1 components.', 'Redundancy is expensive - your diagram should justify N+1 vs 2N for our 10-server scope.'),
(68, 23, 2, 'Section 5.2 & Rack Power and Load Calculations', 'videos/energy/wk5_sec52.mp4', 'Rack power density; Power budgeting per breaker; Total facility load and PUE multiplier; Power factor; Three-phase load balancing; Breaker coordination', 'Upload full facility power design for 10 servers: IT load, cooling overhead, UPS kVA, generator sizing, and balanced three-phase PDU layout across two racks.', 'Unbalanced three-phase loading overheats one leg - show amperes per phase on your PDU plan.'),
(69, 23, 3, 'Section 5.3 & Power Monitoring and Efficiency', 'videos/energy/wk5_sec53.mp4', 'DCIM platforms; Metering at utility, UPS, and PDU; Demand response; Power capping; Efficiency curves at partial load', 'Draft a metering plan: which points need meters to compute accurate PUE and rack-level headroom; upload table with meter location and metric collected.', 'You cannot manage what you do not measure - granular metering is how the sustainability capstone stays honest.'),
(70, 24, 1, 'Section 6.1 & Solar Energy Systems', 'videos/energy/wk6_sec61.mp4', 'Photovoltaic cells; Panel ratings vs real output; Atlanta peak sun hours (~5.29); Inverters DC to AC; Array sizing for 50% solar target; Grid interconnection', 'Upload solar array design: panel count, footprint, inverter capacity, and estimated monthly kWh using Atlanta peak sun hours for the Week 5 facility load.', 'Solar sizing is arithmetic, not guesswork - tie panel count directly to the IT load you calculated in Week 5.'),
(71, 24, 2, 'Section 6.2 & Renewable Energy Integration and Grid Strategy', 'videos/energy/wk6_sec62.mp4', '50/40/10 energy model (solar, CARES renewables, gas fallback); Georgia Power CARES program; Battery storage smoothing; LCOE and grid price trends', 'Upload monthly cost projection comparing 50/40/10 mix vs 100% grid for your facility load; note which tier covers each percentage.', 'The community cloud''s energy story is economic as well as environmental - show dollars alongside kWh.'),
(72, 24, 3, 'Section 6.3 & Environmental Policy and Clean Data Center Capstone', 'videos/energy/wk6_sec63.mp4', 'Environmental metrics as operational data; Supply chain and refurbished hardware; Public transparency; State compliance; Event sourcing for auditability', 'Upload the clean data center capstone document: power redundancy, cooling selection with hybrid justification, solar and 50/40/10 model, PUE target, and one-page environmental accountability statement.', 'This document joins the cloud business proposal and security addendum - it is the technical foundation that makes community-cloud environmental claims credible.');

INSERT INTO `assignment` (`assignmentid`, `videoid`, `studentid`, `miniokey`, `status`, `feedback`, `submitted_at`) VALUES
(1, 2, 1, 'assignments/netsec/marcus_wk1_osi_map.pdf', 'unsatisfactory', 'Missing layer labels on two connections & please resubmit.', '2026-01-10 11:22:00'),
(2, 8, 1, 'assignments/netsec/marcus_wk3_firewall.pdf', 'submitted', NULL, '2026-01-12 11:36:00'),
(3, 5, 2, 'assignments/netsec/tanya_wk2_subnet.pdf', 'submitted', NULL, '2026-01-12 12:29:00'),
(4, 8, 2, 'assignments/netsec/tanya_wk3_firewall.pdf', 'satisfactory', 'Clean rule set. Nice work documenting established connections.', '2026-01-13 12:36:00'),
(5, 20, 3, 'assignments/orchestration/james_wk1_terminal.pdf', 'submitted', NULL, '2026-01-12 13:22:00'),
(6, 23, 3, 'assignments/orchestration/james_wk2_hangman.cpp', 'satisfactory', 'Monolithic Hangman compiles and runs. Ready to refactor.', '2026-01-13 13:29:00'),
(7, 20, 4, 'assignments/orchestration/keisha_wk1_terminal.pdf', 'satisfactory', 'VS Code setup looks good.', '2026-01-13 14:22:00'),
(8, 26, 4, 'assignments/orchestration/keisha_wk3_terminal_sim.cpp', 'satisfactory', 'Tree simulator handles cd and mkdir correctly.', '2026-01-15 14:36:00'),
(9, 41, 5, 'assignments/cloud/david_wk2_hangman.js', 'satisfactory', 'Refactored Hangman functions are clean and readable.', '2026-01-10 15:29:00'),
(10, 44, 5, 'assignments/cloud/david_wk3_services.html', 'unsatisfactory', 'Service cards render but Order object not logged on click & fix event handler.', '2026-01-11 15:36:00'),
(11, 38, 6, 'assignments/cloud/angela_wk2_objects.js', 'satisfactory', 'Service, Customer, Order classes instantiate correctly.', '2026-01-10 16:22:00'),
(12, 41, 6, 'assignments/cloud/angela_wk3_services.zip', 'unsatisfactory', 'Missing fetch() for news API on home page.', '2026-01-11 16:29:00'),
(13, 56, 7, 'assignments/energy/terrence_wk1_rack.pdf', 'unsatisfactory', 'PDU load estimate missing & add watt calculations.', '2026-01-11 17:22:00'),
(14, 62, 7, 'assignments/energy/terrence_wk3_cooling_memo.pdf', 'submitted', NULL, '2026-01-13 17:36:00'),
(15, 59, 8, 'assignments/energy/michelle_wk2_power.pdf', 'submitted', NULL, '2026-01-13 10:29:00'),
(16, 62, 8, 'assignments/energy/michelle_wk3_cooling_memo.pdf', 'satisfactory', 'Strong DX vs CRAH comparison for Atlanta climate.', '2026-01-14 10:36:00'),
(17, 2, 9, 'assignments/netsec/andre_wk1_osi_map.pdf', 'submitted', NULL, '2026-01-13 11:22:00'),
(18, 5, 9, 'assignments/netsec/andre_wk2_subnet.pdf', 'satisfactory', 'Subnet math and diagram both correct.', '2026-01-14 11:29:00'),
(19, 2, 10, 'assignments/netsec/latoya_wk1_osi_map.pdf', 'satisfactory', 'Excellent layer annotations on pod diagram.', '2026-01-09 12:22:00'),
(20, 8, 10, 'assignments/netsec/latoya_wk3_firewall.pdf', 'satisfactory', 'iptables rules tested and documented.', '2026-01-11 12:36:00'),
(21, 23, 11, 'assignments/orchestration/brian_wk2_hangman.cpp', 'satisfactory', 'Raw Hangman runs & ready for function refactor.', '2026-01-11 13:29:00'),
(22, 26, 11, 'assignments/orchestration/brian_wk3_terminal_sim.cpp', 'unsatisfactory', 'touch command not implemented & add before resubmit.', '2026-01-12 13:36:00'),
(23, 20, 12, 'assignments/orchestration/renee_wk1_terminal.pdf', 'satisfactory', 'Hello World compile screenshot accepted.', '2026-01-11 14:22:00'),
(24, 23, 12, 'assignments/orchestration/renee_wk2_hangman.cpp', 'unsatisfactory', 'Infinite loop on invalid input & add input validation.', '2026-01-12 14:29:00'),
(25, 38, 13, 'assignments/cloud/carlos_wk2_objects.js', 'unsatisfactory', 'Order class missing status field.', '2026-01-12 15:22:00'),
(26, 44, 13, 'assignments/cloud/carlos_wk3_services.zip', 'submitted', NULL, '2026-01-14 15:36:00'),
(27, 41, 14, 'assignments/cloud/nicole_wk3_services.zip', 'submitted', NULL, '2026-01-14 16:29:00'),
(28, 44, 14, 'assignments/cloud/nicole_wk3_api_fetch.js', 'satisfactory', 'News API cards render on home page.', '2026-01-15 16:36:00'),
(29, 56, 15, 'assignments/energy/kevin_wk1_rack.pdf', 'submitted', NULL, '2026-01-09 17:22:00'),
(30, 59, 15, 'assignments/energy/kevin_wk2_power.pdf', 'satisfactory', 'N+1 analysis shows correct headroom.', '2026-01-10 17:29:00'),
(31, 56, 16, 'assignments/energy/jasmine_wk1_rack.pdf', 'satisfactory', 'Clear rack elevation with PDU placement.', '2026-01-10 10:22:00'),
(32, 62, 16, 'assignments/energy/jasmine_wk3_cooling_memo.pdf', 'satisfactory', 'Well-reasoned chilled-water recommendation.', '2026-01-12 10:36:00');

INSERT INTO `channel` (`channelid`, `cohortid`, `type`, `name`) VALUES
(1, 1, 'general', 'General'),
(2, 1, 'division', 'Network Security'),
(3, 1, 'division', 'Data Center Orchestration'),
(4, 1, 'division', 'Cloud Architect'),
(5, 1, 'division', 'Energy'),
(6, 1, 'direct', NULL),
(7, 1, 'direct', NULL),
(8, 2, 'general', 'General'),
(9, 2, 'division', 'Network Security'),
(10, 2, 'division', 'Data Center Orchestration'),
(11, 2, 'division', 'Cloud Architect'),
(12, 2, 'division', 'Energy'),
(13, 2, 'direct', NULL),
(14, 2, 'direct', NULL);

INSERT INTO `channel_member` (`channelid`, `member_type`, `member_id`) VALUES
(1, 'student', 1),
(1, 'student', 2),
(1, 'student', 3),
(1, 'student', 4),
(1, 'student', 5),
(1, 'student', 6),
(1, 'student', 7),
(1, 'student', 8),
(1, 'admin', 1),
(8, 'student', 9),
(8, 'student', 10),
(8, 'student', 11),
(8, 'student', 12),
(8, 'student', 13),
(8, 'student', 14),
(8, 'student', 15),
(8, 'student', 16),
(8, 'admin', 2),
(2, 'student', 1),
(2, 'student', 2),
(3, 'student', 3),
(3, 'student', 4),
(4, 'student', 5),
(4, 'student', 6),
(5, 'student', 7),
(5, 'student', 8),
(9, 'student', 9),
(9, 'student', 10),
(10, 'student', 11),
(10, 'student', 12),
(11, 'student', 13),
(11, 'student', 14),
(12, 'student', 15),
(12, 'student', 16),
(2, 'admin', 1),
(3, 'admin', 1),
(4, 'admin', 1),
(5, 'admin', 1),
(9, 'admin', 2),
(10, 'admin', 2),
(11, 'admin', 2),
(12, 'admin', 2),
(6, 'admin', 1),
(6, 'student', 1),
(7, 'admin', 1),
(7, 'student', 5),
(13, 'admin', 2),
(13, 'student', 9),
(14, 'admin', 2),
(14, 'student', 13);

INSERT INTO `messages` (`messagesid`, `channelid`, `sender_type`, `sender_id`, `content`, `sendtime`) VALUES
(1, 1, 'admin', 1, 'Welcome to Cohort 1! This program has four division tracks & Network Security, Data Center Orchestration, Cloud Architect, and Energy. General channel is for cross-track announcements.', '2026-01-06 09:00:00'),
(2, 1, 'admin', 3, 'Hi everyone & Sandra from platform ops. I drop org-wide updates here when we have community-cloud milestones.', '2026-01-06 09:15:00'),
(3, 1, 'student', 5, 'Cloud track checking in & finished my Website Blueprint wireframe for a local tutoring business. Feedback welcome in division channel.', '2026-01-06 14:22:00'),
(4, 1, 'admin', 1, 'Nice start David. Remember Week 1 Cloud goal: understand how software maps to a real service-ordering site before you write backend code.', '2026-01-06 14:45:00'),
(5, 1, 'student', 3, 'Orchestration & anyone else stuck on the raw Hangman loop? My lives counter decrements twice sometimes.', '2026-01-07 11:03:00'),
(6, 2, 'student', 1, 'For spine-leaf week & do we need to show STP blocked ports on the diagram or just label redundant links?', '2026-01-13 16:10:00'),
(7, 2, 'admin', 1, 'Label redundant links and note which STP blocks. Full STP config comes in the build phase.', '2026-01-13 16:28:00'),
(8, 2, 'student', 2, 'iptables lab & should NFS rules allow the whole subnet or just the client IP?', '2026-01-14 10:05:00'),
(9, 2, 'student', 1, 'Denise said client IP only in office hours & least privilege.', '2026-01-14 10:18:00'),
(10, 5, 'student', 7, 'Energy track & CRAC vs CRAH video finally clicked when Patricia mapped it to our Atlanta humidity.', '2026-01-15 13:40:00'),
(11, 5, 'admin', 1, 'Great & facilities decisions directly affect the community cloud environmental profile.', '2026-01-15 14:02:00'),
(12, 3, 'student', 3, 'RAID lab done in VirtualBox. mdadm survived my simulated disk pull & satisfying.', '2026-01-16 08:55:00'),
(13, 3, 'student', 4, 'C++ to JS port is weirdly fun. Hangman reads the same but console.log beats cout for quick tests.', '2026-01-16 09:12:00'),
(14, 4, 'student', 6, 'Flask /services route working. My front-end fetch finally returns JSON instead of hardcoded arrays.', '2026-01-20 17:30:00'),
(15, 4, 'admin', 1, 'That is the Week 4 Cloud milestone & share your repo link in division if you want peer review.', '2026-01-20 17:44:00'),
(16, 6, 'student', 1, 'Thanks for the DM Denise & submitting firewall capstone tonight.', '2026-01-21 19:05:00'),
(17, 6, 'admin', 1, 'Tag me if east-west rule set gets confusing on the pod diagram.', '2026-01-21 19:11:00'),
(18, 8, 'admin', 2, 'Cohort 2 welcome! Same four tracks & check your division channel for track-specific labs.', '2026-01-06 09:00:00'),
(19, 8, 'student', 11, 'Orchestration here. Bit masking project & my network address output is off by one on broadcast. Common mistake?', '2026-01-08 12:20:00'),
(20, 8, 'admin', 2, 'Check your AND mask on the host bits & rewatch Session 2.3 binary segment.', '2026-01-08 12:35:00'),
(21, 8, 'student', 15, 'Energy track & when do we walk the actual cohort lab space? Need to validate aisle layout.', '2026-01-09 15:00:00'),
(22, 8, 'admin', 2, 'Facilities walkthrough is Week 6 capstone. Weeks 1 & 5 are async videos plus optional sync Q&A.', '2026-01-09 15:18:00'),
(23, 9, 'student', 9, 'Subnet calculator done. Finally understand CIDR after drawing it three times.', '2026-01-14 20:01:00'),
(24, 9, 'student', 10, 'Spine-leaf diagram uploaded & used four leaf switches like the rubric example.', '2026-01-14 20:14:00'),
(25, 9, 'admin', 2, 'Save your configs and diagrams & we reference them during the community cloud build.', '2026-01-14 20:30:00'),
(26, 12, 'student', 15, 'N+1 power analysis & is generator capacity separate from UPS sizing in the rubric?', '2026-01-17 11:45:00'),
(27, 12, 'admin', 2, 'Separate sections. UPS covers ride-through; generator is extended outage & show both calculations.', '2026-01-17 12:00:00'),
(28, 11, 'student', 13, 'RAG chatbot returning generic answers & how many markdown files minimum for knowledge base?', '2026-01-18 16:22:00'),
(29, 11, 'student', 14, 'I used five short docs on auto repair services. Quality beats quantity.', '2026-01-18 16:40:00'),
(30, 10, 'student', 12, 'Express /servers route done. Dashboard cards pull live JSON & feels like real orchestration work.', '2026-01-19 09:30:00'),
(31, 10, 'admin', 2, 'That is the Week 6 orchestration target. Next step: normalized logs schema with JOINs.', '2026-01-19 09:48:00'),
(32, 12, 'student', 16, 'Sustainability profile draft done & heat recovery section was the hardest part.', '2026-01-19 14:15:00'),
(33, 1, 'student', 5, 'Cloud track & Docker deploy to Render worked. Public URL in my assignment submission.', '2026-01-22 18:00:00'),
(34, 1, 'student', 7, 'Energy + Cloud overlap on community cloud environmental commitments is interesting & reading both tracks.', '2026-01-22 18:12:00'),
(35, 5, 'student', 8, 'Hot aisle containment question: partial vs full containment for our small lab?', '2026-01-21 10:00:00'),
(36, 3, 'admin', 1, 'Orchestration & save VirtualBox snapshots before RAID failure simulation. Makes retry faster.', '2026-01-23 08:30:00'),
(37, 13, 'admin', 2, 'Andre & subnet question answered in DM. Office hours tomorrow if still stuck.', '2026-01-15 21:00:00'),
(38, 13, 'student', 9, 'Will do, thanks Robert.', '2026-01-15 21:04:00'),
(39, 2, 'student', 2, 'Finished NFS lab. Mount works but only after I fixed rpcbind & worth adding to FAQ.', '2026-01-22 07:50:00'),
(40, 8, 'admin', 3, 'Org-wide reminder: community cloud governance workshop is mandatory for all tracks before build week.', '2026-01-24 08:00:00');