# Docker Setup Guide (WSL2 + Windows CLI)

> This is **Step 1 of [setup.md](setup.md)** — the Docker deep-dive (daemon, loopback binding, corporate
> CA, dependency restore). New here? Start at [setup.md](setup.md) and come back when it sends you here.

## 1. Why we use this setup
This configuration replaces **Docker Desktop** for several reasons:
* **No licensing restrictions:** Avoids paid licenses for JDG (B2B) or Business users.
* **Performance:** It is faster and uses fewer system resources than Docker Desktop.
* **Production Environment:** It is closer to real production Linux servers.
* **Compatibility:** Works better for CI/CD and GitLab Runner workflows.

### Architecture
* **Docker Engine (Server):** Runs inside **WSL2 (Ubuntu)**.
* **Docker CLI (Client):** Runs on **Windows**.
* **Connection:** Communication via **TCP port 2375, bound to loopback (`127.0.0.1`) only**.

> **CRITICAL SECURITY PROTOCOL:** The Docker daemon MUST only listen on loopback
> (`tcp://127.0.0.1:2375`). Binding to `0.0.0.0` is strictly prohibited as it opens
> unauthenticated host root access to the entire subnet.
>
> Port 2375 is the plaintext, unauthenticated Docker API; this guide binds it strictly to
> `127.0.0.1`, so it is reachable only from the same machine (the Windows CLI reaches the
> WSL2 engine over loopback).


---

## 2. WSL2 Configuration (The Server)

### Step A: Install the Docker Engine (`docker-ce`)
This setup uses the upstream Docker Engine, **not** Docker Desktop and **not** the
`docker.io` apt package. Install `docker-ce` inside your WSL2 Ubuntu distribution:

```bash
# Remove any conflicting distro packages first
sudo apt remove -y docker docker-engine docker.io containerd runc 2>/dev/null || true

# Add Docker's official apt repository
sudo apt update
sudo apt install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
  sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install the engine + CLI + buildx/compose plugins
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

Add your user to the `docker` group so you do not need `sudo` for every command
(log out / restart WSL afterwards for it to take effect):

```bash
sudo usermod -aG docker $USER
```

### Step B: Configure the Docker Daemon
1.  Edit the config file:
    ```bash
    sudo nano /etc/docker/daemon.json
    ```
2.  Paste this configuration to expose the API on **loopback only**:
    ```json
    {
      "hosts": ["unix:///var/run/docker.sock", "tcp://127.0.0.1:2375"]
    }
    ```
    > **CRITICAL SECURITY PROTOCOL:** The Docker daemon MUST only listen on loopback
    > (`tcp://127.0.0.1:2375`). Binding to `0.0.0.0` is strictly prohibited as it opens
    > unauthenticated host root access to the entire subnet.

### Step C: Fix Systemd Conflict
1.  Create an override folder:
    ```bash
    sudo mkdir -p /etc/systemd/system/docker.service.d
    sudo nano /etc/systemd/system/docker.service.d/override.conf
    ```
2.  Add these lines to clear default settings:
    ```ini
    [Service]
    ExecStart=
    ExecStart=/usr/bin/dockerd
    ```

### Step D: Enable Systemd
1.  Edit `/etc/wsl.conf`:
    ```bash
    sudo nano /etc/wsl.conf
    ```
2.  Add these lines:
    ```ini
    [boot]
    systemd=true
    ```
3.  **Restart WSL** in Windows PowerShell: `wsl --shutdown`.

---

## 3. Windows Configuration (The Client)

### Step A: Install CLI
Install the Docker client using Scoop:
```powershell
scoop install docker
```

### Step B: Set Global Variable
Run this once in PowerShell (as Administrator) so all apps can find Docker:
```powershell
[System.Environment]::SetEnvironmentVariable("DOCKER_HOST", "tcp://127.0.0.1:2375", "User")
```

### Step C: Setup the "Lazy Loader" Profile
Open your profile (`notepad $PROFILE`) and add the function to start Docker only when you use it. This keeps your terminal startup time very fast.

```powershell
# Docker Lazy Loader: Checks if Docker is running before executing commands
function docker {
    $port = 2375
    $check = New-Object System.Net.Sockets.TcpClient
    try {
        $wait = $check.BeginConnect("127.0.0.1", $port, $null, $null)
        if (!$wait.AsyncWaitHandle.WaitOne(100)) { throw "timeout" }
        $check.EndConnect($wait)
    } catch {
        Write-Host "--- WSL Docker is down. Starting... ---" -ForegroundColor Cyan
        wsl -d Ubuntu -u root service docker start
        Start-Sleep -s 2
    } finally {
        $check.Close()
    }
    & (where.exe docker.exe | Select-Object -First 1) @args
}
```

> **Technical Note:** The command above uses `-d Ubuntu`. If you install a different WSL distribution (e.g., Debian), you must update the distribution name in this function inside your `$PROFILE`.

---

## 4. Corporate SSL Certificates (Godeltech)
If you get "certificate signed by unknown authority" errors when pulling images, you must add the corporate certificate to the WSL trust store.

### Step-by-Step Installation:
1.  **Download the certificate** directly in the WSL terminal:
    ```bash
    wget "https://howto.godeltech.com/download/attachments/102301700/CertEmulationCA.crt?version=1&modificationDate=1723558757976&api=v2" -O CertEmulationCA.crt
    ```

2.  **Import to WSL trust store:**
    ```bash
    # Create the target directory
    sudo mkdir -p /usr/local/share/ca-certificates/godel
    
    # Move the file
    sudo mv CertEmulationCA.crt /usr/local/share/ca-certificates/godel/CertEmulationCA.crt
    
    # Update the certificates list
    sudo update-ca-certificates
    
    # Restart Docker to apply changes
    sudo service docker restart
    ```

### Reference Links:
* [HowTo: Adding Symantec Certificate](https://howto.godeltech.com/display/KB/Adding+Symantec+Certificate+to+an+Application+Specific+Trust+Store)
* [HowTo: WSL2 + Docker Setup (Windows)](https://howto.godeltech.com/pages/viewpage.action?pageId=147652634)

> **You do NOT need to set `HTTP_PROXY`/`HTTPS_PROXY`.** The corporate egress is a **transparent**
> TLS-intercepting proxy — connectivity works once the CA above is trusted; there is no proxy URL to
> configure. The CA install in this section, plus rebuilding the images
> (`bash scripts/build_sandbox_images.sh`, which stages the CA from `CORP_CA_PATH` into the build
> context), is the only mandatory step. See §6 for how dependency restore copes with this network.

---

## 5. How to Verify
1.  Open a new PowerShell window.
2.  Type `docker ps`.
3.  If WSL is off, you will see "Starting...". After a few seconds, you will see the container list.

---

## 6. Dependency Restore Behind the Corporate Network (NU1301 & friends)

The runtime gates run dependency restore (`dotnet restore` / `go mod download` / `npm ci` /
`pip install`) in a **network-ON** phase, then build/test with **network OFF**. Behind the
transparent corporate proxy this used to fail with `NU1301: Unable to load the service index` (and
`Resource temporarily unavailable`), which the orchestrator classifies as an `ENVIRONMENT/NETWORK
HALT` and refuses to "fix" by rerouting the Developer.

**Root cause:** not "no route" — the proxy/antivirus **drops bursts of parallel TLS connections**
that the restore opens. Two further factors made it chronic: the offline fallback baked into the
.NET image covered only a handful of packages, and restore/build run in **separate** containers each
with a fresh `--tmpfs /tmp`, so anything restored online was discarded before the build.

**How it is solved (no action needed beyond §4 + image rebuild):**

1. **Throttle.** The .NET image's `/NuGet.Config` sets `maxHttpRequestsPerSource=1` and the restore
   runs `dotnet restore --disable-parallel` with up to 3 attempts — requests are serialized, so the
   proxy stops dropping the burst.
2. **Persistent cache volume.** Each stack mounts a named docker volume
   (`sdlc-cache-{python,go,node,dotnet}`, at `/cache`) for its package-download cache. It is
   **read-write only during restore** and **read-only** for build/test (so adversarial test code
   cannot poison it). The first run warms it online; every later run/container resolves **offline**.
   Inspect with `docker volume ls | grep sdlc-cache`; reset (forces a fresh online warm) with
   `docker volume rm sdlc-cache-dotnet`.
3. **Wider .NET prewarm.** The image bakes the common test/util packages into an offline fallback so
   even the very first run rarely needs the network.

**If your site uses an EXPLICIT proxy** (not transparent): set `HTTP_PROXY` / `HTTPS_PROXY` /
`NO_PROXY` (or lowercase) in the **WSL** shell that launches the orchestrator. The sandbox adapter
auto-propagates them into the network-ON restore phase only (the isolated test phase stays clean) —
no code change required. Example (`~/.bashrc`):

```bash
export HTTPS_PROXY="http://proxy.corp:8080"
export HTTP_PROXY="http://proxy.corp:8080"
export NO_PROXY="localhost,127.0.0.1,.corp"
```