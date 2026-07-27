Feature: User Matching
  As a reconciliation analyst
  I want Replicon users matched to ServiceNow users
  So that hours can be compared between the two systems

  Scenario: Exact normalised name match is auto-accepted
    Given a Replicon user named "John Smith"
    And a ServiceNow user named "John Smith" with ID "jsmith"
    When I match users
    Then the match status is auto_accepted
    And the match method is exact_name

  Scenario: Last-First name format is normalised before matching
    Given a Replicon user named "Smith, John"
    And a ServiceNow user named "John Smith" with ID "jsmith"
    When I match users
    Then the match status is auto_accepted

  Scenario: Unrecognisable user has no match
    Given a Replicon user named "ZZZNOBODY XYZABC"
    And no matching ServiceNow user
    When I match users
    Then the match status is no_match or rejected

  Scenario: Approved mapping overrides auto-generated matches
    Given an approved user mapping with a manual correction
    When I run user matching with the approved mapping
    Then the corrected entry takes precedence
