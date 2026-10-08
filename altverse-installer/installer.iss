; AltVerse Browser installer - includes a model picker wizard page.
#define MyAppName "AltVerse Browser"
#define MyAppVersion "1.0"

[Setup]
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\AltVerse
OutputDir=C:\Users\Nikolas\Desktop
OutputBaseFilename=AltVerseSetup
SetupIconFile=icon.ico
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
WizardStyle=modern

[Files]
Source: "..\altverse\app.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "Launcher.bat"; DestDir: "{app}"; DestName: "AltVerse.bat"; Flags: ignoreversion
Source: "DownloadModel.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "icon.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autodesktop}\AltVerse Browser"; Filename: "{app}\AltVerse.bat"; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"

[Run]
Filename: "winget"; Parameters: "install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements"; Description: "Install Python 3.12 (required, one-time admin prompt)"; Flags: postinstall; Check: NeedsPython
Filename: "winget"; Parameters: "install --id AMD.LemonadeServer -e --accept-source-agreements --accept-package-agreements"; Description: "Install Lemonade Server (AI backend, one-time admin prompt)"; Flags: postinstall; Check: NeedsLemonade
Filename: "{app}\DownloadModel.bat"; Description: "Download the AI model now (required before first launch)"; Flags: postinstall
Filename: "{app}\AltVerse.bat"; Description: "Launch AltVerse Browser now"; Flags: postinstall nowait skipifsilent

[Code]
var
  ModelPage: TWizardPage;
  RadioOpts: array of TRadioButton;
  OptModels: array of String;
  OptCtx: array of String;
  OptCount: Integer;
  VRAM_MB: Integer;

function CmdOk(const Cmd: String): Boolean;
var
  Res: Integer;
begin
  Result := Exec('cmd.exe', '/c ' + Cmd + ' >nul 2>&1', '',
    SW_HIDE, ewWaitUntilTerminated, Res) and (Res = 0);
end;

function NeedsPython(): Boolean;
begin
  Result := not CmdOk('py -3 --version');
end;

function NeedsLemonade(): Boolean;
begin
  Result := True;
  if CmdOk('where lemonade') then Result := False
  else if FileExists(ExpandConstant('{localappdata}\lemonade_server\bin\lemonade.exe')) then Result := False
  else if FileExists(ExpandConstant('{pf}\lemonade_server\bin\lemonade.exe')) then Result := False;
end;

function DetectVRAM_MB(): Integer;
var
  Tmp: String;
  S: AnsiString;
  Num: String;
  I: Integer;
begin
  Result := 0;
  Tmp := ExpandConstant('{tmp}\vram.txt');
  Exec('cmd.exe', '/c nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits > "' + Tmp + '" 2>nul', '', SW_HIDE, ewWaitUntilTerminated, I);
  if LoadStringFromFile(Tmp, S) then
  begin
    S := Trim(S);
    I := Pos(#10, S);
    if I > 0 then S := Copy(S, 1, I - 1);
    S := Trim(S);
    Num := '';
    for I := 1 to Length(S) do
      if (S[I] >= '0') and (S[I] <= '9') then Num := Num + S[I];
    if Num <> '' then Result := StrToIntDef(Num, 0);
  end;
  DeleteFile(Tmp);
end;

function FindModel(const Sub: String): Integer;
var
  I: Integer;
begin
  Result := -1;
  for I := 0 to OptCount - 1 do
    if Pos(Sub, Uppercase(OptModels[I])) > 0 then
    begin
      Result := I;
      Exit;
    end;
end;

function ModelExists(const ID: String): Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 0 to OptCount - 1 do
    if CompareText(OptModels[I], ID) = 0 then
    begin
      Result := True;
      Exit;
    end;
end;

procedure AddModelOption(const DispName, ModelID, Ctx: String);
var
  I: Integer;
begin
  if ModelExists(ModelID) then Exit;
  I := OptCount;
  OptCount := OptCount + 1;
  SetLength(OptModels, OptCount);
  SetLength(OptCtx, OptCount);
  SetLength(RadioOpts, OptCount);
  OptModels[I] := ModelID;
  OptCtx[I] := Ctx;
  RadioOpts[I] := TRadioButton.Create(ModelPage);
  RadioOpts[I].Parent := ModelPage.Surface;
  RadioOpts[I].Left := 0;
  RadioOpts[I].Top := 64 + I * 26;
  RadioOpts[I].Width := ModelPage.SurfaceWidth;
  RadioOpts[I].Caption := DispName;
end;

procedure ScanLocalModels;
var
  Tmp: String;
  S: AnsiString;
  SL: TStringList;
  I, J, Res: Integer;
  Line, Name: String;
begin
  Tmp := ExpandConstant('{tmp}\lelmodels.txt');
  Exec('cmd.exe', '/c lemonade list --downloaded > "' + Tmp + '" 2>nul', '',
    SW_HIDE, ewWaitUntilTerminated, Res);
  if not LoadStringFromFile(Tmp, S) then
  begin
    DeleteFile(Tmp);
    Exit;
  end;
  DeleteFile(Tmp);
  SL := TStringList.Create;
  try
    SL.Text := S;
    for I := 0 to SL.Count - 1 do
    begin
      Line := Trim(SL[I]);
      if Pos('Yes', Line) = 0 then Continue;
      J := 1;
      while (J <= Length(Line)) and (Line[J] <> ' ') and (Line[J] <> #9) do Inc(J);
      Name := Copy(Line, 1, J - 1);
      if Name <> '' then AddModelOption(Name + ' (downloaded)', Name, '4096');
    end;
  finally
    SL.Free;
  end;
end;

function SelectedIdx(): Integer;
var
  I: Integer;
begin
  Result := 0;
  for I := 0 to OptCount - 1 do
    if RadioOpts[I].Checked then
    begin
      Result := I;
      Exit;
    end;
end;

procedure InitializeWizard;
var
  Desc: TNewStaticText;
  RecIdx: Integer;
begin
  VRAM_MB := DetectVRAM_MB();
  ModelPage := CreateCustomPage(wpSelectDir,
    'AI Model', 'Which brain should AltVerse use?');
  Desc := TNewStaticText.Create(ModelPage);
  Desc.Parent := ModelPage.Surface;
  Desc.Left := 0; Desc.Top := 0;
  Desc.Width := ModelPage.SurfaceWidth;
  Desc.Height := 56;
  Desc.Caption := 'Models already downloaded on this PC are listed with (downloaded) '
    + 'and need no download. Poor mans AI is fast and runs on any 6 GB card. '
    + 'The nice 30B is much smarter but needs 16 GB or more VRAM '
    + '(e.g. RTX 3090). You can change this later by editing model.txt in the install folder.';
  Desc.WordWrap := True;
  Desc.AutoSize := False;

  OptCount := 0;
  AddModelOption('Poor mans AI - Qwen3 4B (fast, works everywhere)',
    'Qwen3-4B-Instruct-2507-GGUF', '4096');
  AddModelOption('Nice 30B - Qwen3-Coder 30B (best quality, 16 GB+ VRAM)',
    'Qwen3-Coder-30B-A3B-Instruct-Q4_K_M', '8192');
  ScanLocalModels();

  RecIdx := -1;
  if VRAM_MB >= 20000 then RecIdx := FindModel('30B');
  if RecIdx < 0 then RecIdx := FindModel('-4B-');
  if RecIdx < 0 then RecIdx := 0;
  RadioOpts[RecIdx].Caption := RadioOpts[RecIdx].Caption + ' (recommended)';
  RadioOpts[RecIdx].Checked := True;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Picked: String;
begin
  Result := True;
  if CurPageID = ModelPage.ID then
  begin
    Picked := Uppercase(OptModels[SelectedIdx()]);
    if (Pos('30B', Picked) > 0) and (VRAM_MB < 20000) then
      Result := MsgBox('That model wants an NVIDIA GPU with 16 GB or more VRAM and downloads about 17 GB. Continue?', mbConfirmation, MB_YESNO) = IDYES;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Idx: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    Idx := SelectedIdx();
    SaveStringToFile(ExpandConstant('{app}\model.txt'),
      OptModels[Idx] + #13#10 + OptCtx[Idx] + #13#10, False);
  end;
end;
