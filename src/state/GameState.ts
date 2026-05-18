import { Player } from '../entities/Player';
import type { PlayerSnapshot } from '../entities/Player';

interface ServerLocalPlayer {
  id: string;
  name: string;
  normalized_name?: string;
  character_id: string;
  x: number;
  y: number;
  direction: string;
  level?: number;
  coins?: number;
}

interface ServerRemotePlayer {
  id: string;
  name: string;
  x: number;
  y: number;
  direction?: string;
  character_id?: string;
}

interface StateSyncInput {
  player: ServerLocalPlayer;
  online_players: Record<string, ServerRemotePlayer>;
}

type PositionUpdateMap = Record<string, { x: number; y: number; direction: string }>;

export class GameState {
  private localPlayer: Player | null = null;
  private remotePlayersMap: Map<string, Player> = new Map();

  applyStateSync(msg: StateSyncInput): void {
    const lp = msg.player;
    this.localPlayer = new Player({
      id: lp.id,
      name: lp.name,
      x: lp.x,
      y: lp.y,
      direction: lp.direction,
      characterId: lp.character_id,
    });

    this.remotePlayersMap.clear();
    for (const [pid, rp] of Object.entries(msg.online_players)) {
      if (pid === lp.id) continue;
      this.remotePlayersMap.set(pid, new Player({
        id: rp.id,
        name: rp.name,
        x: rp.x,
        y: rp.y,
        direction: rp.direction ?? 'down',
        characterId: rp.character_id ?? '',
      }));
    }
  }

  applyStateUpdate(players: PositionUpdateMap): void {
    for (const [pid, pos] of Object.entries(players)) {
      const player = this.remotePlayersMap.get(pid);
      if (player !== undefined) {
        player.applyPositionUpdate(pos.x, pos.y, pos.direction);
      }
    }
  }

  applyPlayerJoined(playerData: ServerRemotePlayer): void {
    if (this.localPlayer !== null && playerData.id === this.localPlayer.id) return;
    this.remotePlayersMap.set(playerData.id, new Player({
      id: playerData.id,
      name: playerData.name,
      x: playerData.x,
      y: playerData.y,
      direction: playerData.direction ?? 'down',
      characterId: playerData.character_id ?? '',
    }));
  }

  applyPlayerLeft(playerId: string): void {
    this.remotePlayersMap.delete(playerId);
  }

  getLocalPlayer(): Player | null {
    return this.localPlayer;
  }

  getRemotePlayers(): Player[] {
    return Array.from(this.remotePlayersMap.values());
  }

  snapshotRemotePlayers(): PlayerSnapshot[] {
    return this.getRemotePlayers().map((p) => p.snapshot());
  }
}
