-- ============================================================
-- AARI Educational Suite - High School Course Schema (Canvas-style)
-- One in-person course: From Infrastructure to Cloud (6 weeks, 2 days per week),
-- with per-day Google slides, enrollment, and daily exit tickets.
-- Notes:
-- * Password columns store bcrypt hashes (strings), NEVER plaintext.
-- * Exit tickets are an ungraded retention signal, not homework:
-- `assignment` on Day describes what the exit ticket is (teacher-authored, student-visible);
-- students submit an optional attachment (`miniokey`) only - no written response.
-- * Teachers are not tied to a course: any teacher can create and manage every course.
-- * Parent tables created before children so FKs resolve.
-- * Safe to re-run in MySQL Workbench: drops existing tables first.
-- * Dummy seed data included below for local dev.
-- Default login password for all seed users: 123123 (override via TEST_PASSWORD in .env).
-- ============================================================

CREATE DATABASE IF NOT EXISTS `highschool` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE `highschool`;
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
 `password` VARCHAR(255) NULL  -- bcrypt; NULL until first password login
);
ALTER TABLE `students` ADD UNIQUE `students_email_unique`(`email`);

CREATE TABLE `teacher`(
 `teacherid` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 `fname` VARCHAR(255) NOT NULL,
 `lname` VARCHAR(255) NOT NULL,
 `email` VARCHAR(255) NOT NULL,
 `password` VARCHAR(255) NULL  -- bcrypt; NULL until first password login
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
 `assignment` TEXT NULL, -- teacher-set description of what the exit ticket is
 `slidelink` VARCHAR(255) NULL
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
(1, 'From Infrastructure to Cloud',
 'A 6-week in-person course (2 days per week) that takes students from what a data center is and their first line of Python to running a language model on their own machine.

Foundations and Programming (Weeks 1-3): What a data center is, servers vs. personal computers, the software lifecycle, and the ethics of data centers. Python data types, I/O, variables, operators, control flow, loops, lists, functions, scope, and libraries. Projects: environment setup, Basic Calculator, Calculator with a Menu, Number Guessing Game, and a refactor with the random library.

Project A - The Computer Class (Weeks 3-5): Objects, constructors, encapsulation, accessors and mutators; networking; computer architecture (CPU, RAM vs. ROM, GPU, motherboard, PCI); data center architecture (operating systems, virtualization, high availability, servers and racks, cooling, PDUs); and energy, from power plants to the grid. Students build a simulated login system, rewrite it to pull live information from their own machine, then estimate the power, cost, and CO2 of a rack of those computers.

AI (Week 6): Scalars, vectors, matrices, datasets, and neural networks, with students building their own labeled dataset; then LLMs, context vectors, tokenization, pre-prompting, RAG, and running a model locally with Ollama.

Each lecture day has its own slide deck and exit ticket - ungraded check-ins on what clicked that day.');

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

INSERT INTO `teacher` (`teacherid`, `fname`, `lname`, `email`, `password`) VALUES
(1, 'Ahmed', 'Kiel-Kamil', 'ahmed.kielkamil@outlook.com', @pw),
(2, 'Grayson', 'Roper', 'gmanroper@gmail.com', @pw),
(3, 'Charles', 'Butler', 'cb3student@gmail.com', @pw);

INSERT INTO `class` (`classid`, `studentid`, `courseid`) VALUES
(1, 1, 1), (2, 2, 1), (3, 3, 1), (4, 4, 1), (5, 5, 1),
(6, 6, 1), (7, 7, 1), (8, 8, 1), (9, 9, 1), (10, 10, 1),
(11, 11, 1), (12, 12, 1), (13, 13, 1), (14, 14, 1), (15, 15, 1);

INSERT INTO `Week` (`weekid`, `courseid`, `title`, `num`) VALUES
(1, 1, 'Foundations', 1),
(2, 1, 'Logic & Repetition', 2),
(3, 1, 'Abstraction', 3),
(4, 1, 'Low Level Computing', 4),
(5, 1, 'Data Center Architecture', 5),
(6, 1, 'AI', 6);

INSERT INTO `Day` (`dayid`, `weekid`, `num`, `title`, `description`) VALUES
(1, 1, 1, 'What Is a Data Center?', 'Servers vs. personal computers, the software lifecycle, why generic software needs more infrastructure than personalized software, and the ethics of data centers. Project: Terminal and Environment Setup.'),
(2, 1, 2, 'Basics of Programming (Python)', 'Data types (int, float, str, bool), print() and input(), variables, and arithmetic and assignment operators. Project: Basic Calculator.'),
(3, 2, 1, 'Control Flow', 'Boolean logic, comparison operators, if/elif/else, and when to nest conditionals. Project: Calculator with a Menu, with a guard against division by zero.'),
(4, 2, 2, 'Loops and Arrays', 'Why repetition matters, while vs. for loops, infinite loops, Python lists, and iterating over a list with an index. Project: Number Guessing Game.'),
(5, 3, 1, 'Functions and Libraries', 'DRY, defining and calling functions, return values, scope, functions as building blocks, and libraries. Project: Refactor the Guessing Game with the random library.'),
(6, 3, 2, 'Objects (Project A Begins)', 'Member variables and functions, __init__ constructors, encapsulation, and accessors and mutators. Project: Simulated Login System.'),
(7, 4, 1, 'Networking', 'What a network is; routers, switches, IP and MAC addressing, traffic, and how network scope grows from a single device to the entire internet.'),
(8, 4, 2, 'Computer Architecture', 'The CPU and fetch-decode-execute, RAM vs. ROM, why GPUs power AI, the motherboard, and PCI expansion slots. Project: Extend the Computer Class.'),
(9, 5, 1, 'Data Center Architecture (Project A Finishes)', 'Operating systems, virtualization, high availability, rack/blade/tower servers, racks and U''s, cooling, and PDUs. Project: Go Live, replacing every hardcoded value with live data.'),
(10, 5, 2, 'Energy', 'Watts vs. kWh, energy sources, generators, transmission and distribution, grid and emissions impacts, and data center best practices. Project: Power Up the Computer Class (kWh, cost, and CO2).'),
(11, 6, 1, 'AI Part 1: Make the Data', 'Why AI needs numbers; scalars, vectors, and matrices; datasets and data transformation; neural network layers and training. Project: Build Your Own Dataset.'),
(12, 6, 2, 'LLMs', 'What an LLM is, context vectors, tokenization, pre-prompting and RAG, and running a model locally with Ollama.');