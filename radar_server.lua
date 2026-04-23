--[[
    radar_server.lua
    TCP server that accepts recording commands from the Python GUI.

    HOW TO USE:
      1. Open mmWave Studio and configure your radar as normal
         (PowerOn, RfEnable, ProfileConfig, ChirpConfig, FrameConfig, etc.)
      2. In the Script editor, open this file and click Run (or press F5).
      3. The log window should show "Radar server started on port 55000".
      4. Now use the Python GUI — it will connect here for every recording.

    COMMANDS (sent as newline-terminated strings over TCP 127.0.0.1:55000):
      "setup"                            -> configure DCA1000 Ethernet/mode
      "record|C:\path\to\file.bin|5000|50"  -> arm DCA, set frame count (5000ms/50ms=100 frames), trigger, wait, stop
      "ping"                             -> health check, returns "pong"
--]]

local PORT = 55000

local server, err = socket.bind("127.0.0.1", PORT)
if not server then
    WriteToLog("ERROR: Could not bind to port " .. PORT .. ": " .. tostring(err) .. "\n", "red")
    return
end
server:settimeout(0)  -- non-blocking accept

WriteToLog("===========================================\n", "green")
WriteToLog(" Radar server started on port " .. PORT .. "\n", "green")
WriteToLog(" Waiting for commands from Python GUI...\n", "green")
WriteToLog("===========================================\n", "green")

-- ── DCA1000 Ethernet + mode configuration ────────────────────────────────────
function setupDCA()
    if ar1.SelectCaptureDevice("DCA1000") ~= 0 then
        WriteToLog("SelectCaptureDevice FAILED\n", "red"); return -1
    end
    WriteToLog("SelectCaptureDevice OK\n", "green")

    if ar1.CaptureCardConfig_EthInit("192.168.33.30", "192.168.33.180",
                                      "12:34:56:78:90:12", 4096, 4098) ~= 0 then
        WriteToLog("CaptureCardConfig_EthInit FAILED\n", "red"); return -1
    end
    WriteToLog("CaptureCardConfig_EthInit OK\n", "green")

    if ar1.CaptureCardConfig_Mode(1, 1, 1, 2, 3, 30) ~= 0 then
        WriteToLog("CaptureCardConfig_Mode FAILED\n", "red"); return -1
    end
    WriteToLog("CaptureCardConfig_Mode OK\n", "green")

    if ar1.CaptureCardConfig_PacketDelay(25) ~= 0 then
        WriteToLog("CaptureCardConfig_PacketDelay FAILED\n", "red"); return -1
    end
    WriteToLog("CaptureCardConfig_PacketDelay OK\n", "green")

    return 0
end

-- ── Record: arm DCA → trigger frame → wait → stop ────────────────────────────
-- frame_period_ms: time between frames in ms (from mmWave Studio FrameConfig).
--   e.g. 50 ms → 20 fps.  Pass 0 to skip dynamic frame-count override.
function recordData(filepath, duration_ms, frame_period_ms)
    WriteToLog("Recording -> " .. filepath .. "  (" .. duration_ms .. " ms)\n", "blue")

    -- Dynamically set frame count so the radar runs for exactly duration_ms.
    -- Without this the radar stops at whatever frame count was set in mmWave Studio.
    if frame_period_ms and frame_period_ms > 0 then
        local num_frames = math.ceil(duration_ms / frame_period_ms)
        WriteToLog("Setting num_frames = " .. num_frames ..
                   "  (period=" .. frame_period_ms .. " ms)\n", "blue")
        -- loopCount=255 matches config5; triggerSelect=1 = software trigger (StartFrame)
        ar1.FrameConfig(0, 0, 255, num_frames, frame_period_ms, 1, 0)
    end

    -- Arm DCA and set output filename
    ar1.CaptureCardConfig_StartRecord(filepath, 1)
    RSTD.Sleep(500)

    -- Start radar frame transmission
    local ret = ar1.StartFrame()
    if ret == 0 then
        WriteToLog("StartFrame OK\n", "green")
    else
        WriteToLog("StartFrame FAILED (ret=" .. tostring(ret) .. ") — is radar configured?\n", "red")
        return -1
    end

    -- Wait for the requested duration
    RSTD.Sleep(duration_ms)

    -- Stop frame transmission — frame may have already ended naturally, so use pcall
    local ok, err = pcall(ar1.StopFrame)
    if ok then
        WriteToLog("StopFrame OK\n", "green")
    else
        WriteToLog("StopFrame note: frame ended naturally (" .. tostring(err) .. ")\n", "blue")
    end

    WriteToLog("Recording done: " .. filepath .. "\n", "green")
    return 0
end

-- ── Main server loop ──────────────────────────────────────────────────────────
while true do
    local client = server:accept()

    if client then
        client:settimeout(30)
        local line, err = client:receive("*l")

        if line then
            WriteToLog("CMD: " .. line .. "\n", "blue")

            local cmd = line:match("^([^|]+)")

            if cmd == "ping" then
                client:send("pong\n")

            elseif cmd == "setup" then
                local status = setupDCA()
                client:send(status == 0 and "setup_ok\n" or "setup_error\n")

            elseif cmd == "record" then
                -- format: record|C:\full\path\file.bin|duration_ms|frame_period_ms
                -- frame_period_ms is optional (omit to skip dynamic frame count)
                local parts = {}
                for p in line:gmatch("[^|]+") do parts[#parts+1] = p end
                local filepath        = parts[2]
                local duration_ms     = tonumber(parts[3])
                local frame_period_ms = tonumber(parts[4])  -- optional

                if filepath and duration_ms then
                    local ok, err = pcall(recordData, filepath, duration_ms, frame_period_ms)
                    if ok then
                        client:send("record_done\n")
                    else
                        WriteToLog("recordData error: " .. tostring(err) .. "\n", "red")
                        client:send("record_error: " .. tostring(err) .. "\n")
                    end
                else
                    WriteToLog("Bad record params: " .. line .. "\n", "red")
                    client:send("record_error: bad params\n")
                end

            else
                client:send("unknown_command\n")
            end
        end

        client:close()
    end

    RSTD.Sleep(50)  -- yield to mmWave Studio UI
end
