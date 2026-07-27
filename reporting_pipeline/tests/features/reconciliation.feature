Feature: Timesheet Reconciliation
  As a finance analyst
  I want to reconcile Replicon and ServiceNow timesheets
  So that I can identify billing discrepancies before invoicing

  Scenario: Matching hours produce zero variance
    Given a Replicon entry with 8 hours on task TASK-001 for user jsmith
    And a ServiceNow entry with 8 hours on task TASK-001 for user jsmith
    When I run reconciliation
    Then the net variance is 0

  Scenario: Hours in ServiceNow but absent from Replicon are flagged
    Given no Replicon entry for task TASK-001
    And a ServiceNow entry with 5 hours on task TASK-001 for user jsmith
    When I run reconciliation
    Then the exception type is missing_in_replicon

  Scenario: Hours in Replicon but absent from ServiceNow are flagged
    Given a Replicon entry with 8 hours on task TASK-001 for user jsmith
    And no ServiceNow entry for that task
    When I run reconciliation
    Then the exception type is missing_in_servicenow

  Scenario: Mismatched hours are flagged
    Given a Replicon entry with 8 hours for user jsmith
    And a ServiceNow entry with 6 hours for user jsmith
    When I run reconciliation
    Then the exception type is hours_mismatch
    And the variance is -2

  Scenario: Replicon hours are conserved through aggregation
    Given Replicon entries totalling 12 hours across two tasks
    When I run reconciliation
    Then Replicon hours before aggregation equals hours after aggregation

  Scenario: ServiceNow data outside the Replicon date window is excluded
    Given a Replicon entry dated 2026-06-01
    And a ServiceNow entry dated 2025-01-01 for the same user and task
    When I run reconciliation
    Then the ServiceNow row is excluded from the comparison
