#!/bin/sh
# One-time setup on a fresh Azure Ubuntu VM (24.04 LTS). The repository is private, so paste this
# file into the VM (nano azure-vm-setup.sh) and run it as the admin user:  sh azure-vm-setup.sh
# Installs Docker, adds 2 GB swap (a 1 GB VM runs out of memory while building the panel),
# opens only SSH/HTTP/HTTPS, and makes a read-only deploy key for cloning the private repository.
set -e

echo "== swap (2 GB)"
if ! swapon --show | grep -q /swapfile; then
  sudo fallocate -l 2G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

echo "== updates + Docker"
sudo apt-get update -y
sudo apt-get install -y ca-certificates curl git ufw unattended-upgrades
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sudo sh
fi
sudo usermod -aG docker "$USER"

echo "== firewall: only 22, 80, 443"
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw --force enable

echo "== deploy key for the private GitHub repository (read-only)"
if [ ! -f "$HOME/.ssh/kapanis_deploy" ]; then
  ssh-keygen -t ed25519 -N "" -C "kapanis-azure-vm" -f "$HOME/.ssh/kapanis_deploy"
  cat >> "$HOME/.ssh/config" <<CFG
Host github.com
  IdentityFile ~/.ssh/kapanis_deploy
  IdentitiesOnly yes
CFG
  chmod 600 "$HOME/.ssh/config"
fi
echo
echo "Add this PUBLIC key on GitHub: repo kapanis -> Settings -> Deploy keys -> Add (read-only, no write access):"
echo
cat "$HOME/.ssh/kapanis_deploy.pub"
echo
echo "Then log out and back in (docker group), and continue with BULUT_KURULUM.md, Azure step 5."
