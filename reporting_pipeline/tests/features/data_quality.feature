Feature: Data Quality
  As a data engineer
  I want input data validated and cleaned consistently
  So that downstream calculations are reliable

  Scenario: Blank Replicon hours are treated as zero
    Given a Replicon entry with blank hours
    When the data is cleaned
    Then the hours value is 0.0

  Scenario: Invalid Replicon date becomes NaT
    Given a Replicon entry with date "not-a-date"
    When the data is cleaned
    Then the date value is NaT

  Scenario: ServiceNow user ID whitespace is stripped
    Given a ServiceNow row with user ID "  jsmith  "
    When the data is cleaned
    Then the user ID is "jsmith"

  Scenario: Missing required Replicon column raises ValidationError
    Given a DataFrame missing the Task Code column
    When I validate Replicon columns
    Then a ValidationError is raised mentioning Task Code

  Scenario: Empty DataFrame raises ValidationError
    Given an empty DataFrame named Replicon
    When I check it is not empty
    Then a ValidationError is raised

  Scenario: Duplicate Replicon keys trigger a warning
    Given two Replicon rows with identical date, user, and task code
    When I check for duplicate keys
    Then a warning is logged

  Scenario: Employee ID trailing .0 is stripped
    Given a Replicon entry with Employee ID "E001.0"
    When the data is cleaned
    Then the employee_id is "E001"
