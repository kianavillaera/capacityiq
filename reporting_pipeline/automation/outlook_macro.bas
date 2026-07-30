Attribute VB_Name = "CIQ_AutoSave"
' ─────────────────────────────────────────────────────────────────────────────
' Outlook VBA Macro — Auto-save IQ Time card attachments
'
' HOW TO INSTALL:
'   1. In Outlook: Alt+F11 → Insert → Module → paste this code → Save
'   2. Go to: Home → Rules → Manage Rules & Alerts → New Rule
'      → "Apply rule on messages I receive"
'      → Condition: "with specific words in the subject" → add "IQ Time card"
'      → Action: "run a script" → select CIQ_AutoSave.SaveTimeCardAttachment
'      → Finish
'
' WHAT IT DOES:
'   When an email with "IQ Time card" in the subject arrives, all .xls/.xlsx
'   attachments are saved to C:\Users\<you>\Downloads\CIQ_incoming\
'   The pipeline then picks them up automatically within the hour.
' ─────────────────────────────────────────────────────────────────────────────

Public Sub SaveTimeCardAttachment(Item As Outlook.MailItem)
    Dim SaveFolder As String
    Dim att As Outlook.Attachment
    Dim savePath As String

    SaveFolder = Environ("USERPROFILE") & "\Downloads\CIQ_incoming\"

    ' Create the folder if it doesn't exist
    If Dir(SaveFolder, vbDirectory) = "" Then
        MkDir SaveFolder
    End If

    ' Save all XLS/XLSX attachments
    For Each att In Item.Attachments
        Dim ext As String
        ext = LCase(Right(att.FileName, 4))
        If ext = ".xls" Or ext = "xlsx" Then
            savePath = SaveFolder & att.FileName
            ' If file already exists, add a timestamp suffix
            If Dir(savePath) <> "" Then
                Dim ts As String
                ts = Format(Now, "YYYYMMDD_HHMMSS")
                savePath = SaveFolder & Left(att.FileName, InStrRev(att.FileName, ".") - 1) _
                           & "_" & ts & Right(att.FileName, Len(att.FileName) - InStrRev(att.FileName, ".") + 1)
            End If
            att.SaveAsFile savePath
        End If
    Next att

    ' Optional: mark the email as read
    Item.UnRead = False
End Sub
