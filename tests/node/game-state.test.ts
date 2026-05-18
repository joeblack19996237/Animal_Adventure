import { describe, expect, it } from 'vitest';
import { Player } from '../../src/entities/Player';
import { GameState } from '../../src/state/GameState';

describe('Player', () => {
  it('stores id, name, position, direction, and characterId on construction', () => {
    const player = new Player({
      id: 'p1',
      name: 'Kitty',
      x: 100,
      y: 200,
      direction: 'down',
      characterId: 'arctic_fox',
    });
    expect(player.id).toBe('p1');
    expect(player.name).toBe('Kitty');
    expect(player.x).toBe(100);
    expect(player.y).toBe(200);
    expect(player.direction).toBe('down');
    expect(player.characterId).toBe('arctic_fox');
  });

  it('updates x, y, direction after applyPositionUpdate', () => {
    const player = new Player({ id: 'p1', name: 'Kitty', x: 0, y: 0, direction: 'down', characterId: 'penguin' });
    player.applyPositionUpdate(300, 400, 'right');
    expect(player.x).toBe(300);
    expect(player.y).toBe(400);
    expect(player.direction).toBe('right');
  });

  it('snapshot returns current values and is stable after subsequent updates', () => {
    const player = new Player({ id: 'p1', name: 'Kitty', x: 0, y: 0, direction: 'down', characterId: 'penguin' });
    const snap = player.snapshot();
    player.applyPositionUpdate(99, 88, 'up');
    expect(snap.x).toBe(0);
    expect(snap.y).toBe(0);
    expect(player.x).toBe(99);
  });
});

const LOCAL_PLAYER = {
  id: 'p1',
  name: 'Kitty',
  normalized_name: 'kitty',
  character_id: 'arctic_fox',
  x: 2715,
  y: 3620,
  direction: 'down',
  level: 0,
  coins: 25,
};

describe('GameState', () => {
  describe('applyStateSync', () => {
    it('sets local player from state_sync player field', () => {
      const gs = new GameState();
      gs.applyStateSync({ player: LOCAL_PLAYER, online_players: {} });
      const local = gs.getLocalPlayer();
      expect(local).not.toBeNull();
      expect(local?.id).toBe('p1');
      expect(local?.x).toBe(2715);
      expect(local?.direction).toBe('down');
      expect(local?.characterId).toBe('arctic_fox');
    });

    it('populates remote players from online_players excluding local player', () => {
      const gs = new GameState();
      gs.applyStateSync({
        player: LOCAL_PLAYER,
        online_players: {
          p1: { id: 'p1', name: 'Kitty', x: 2715, y: 3620, direction: 'down', character_id: 'arctic_fox' },
          p2: { id: 'p2', name: 'Bunny', x: 2700, y: 3600, direction: 'right', character_id: 'penguin' },
        },
      });
      const remotes = gs.getRemotePlayers();
      expect(remotes).toHaveLength(1);
      expect(remotes[0].id).toBe('p2');
    });

    it('clears previous remote players on a second state_sync', () => {
      const gs = new GameState();
      gs.applyStateSync({
        player: LOCAL_PLAYER,
        online_players: {
          p2: { id: 'p2', name: 'B', x: 0, y: 0, direction: 'down', character_id: 'penguin' },
        },
      });
      gs.applyStateSync({ player: LOCAL_PLAYER, online_players: {} });
      expect(gs.getRemotePlayers()).toHaveLength(0);
    });
  });

  describe('applyStateUpdate', () => {
    it('updates a known remote player position from state_update players map', () => {
      const gs = new GameState();
      gs.applyStateSync({
        player: LOCAL_PLAYER,
        online_players: {
          p2: { id: 'p2', name: 'B', x: 100, y: 100, direction: 'down', character_id: 'penguin' },
        },
      });
      gs.applyStateUpdate({ p2: { x: 200, y: 300, direction: 'left' } });
      const remote = gs.getRemotePlayers().find((p) => p.id === 'p2');
      expect(remote?.x).toBe(200);
      expect(remote?.y).toBe(300);
      expect(remote?.direction).toBe('left');
    });

    it('ignores updates for unknown player ids without throwing', () => {
      const gs = new GameState();
      gs.applyStateSync({ player: LOCAL_PLAYER, online_players: {} });
      expect(() => gs.applyStateUpdate({ p99: { x: 1, y: 2, direction: 'up' } })).not.toThrow();
    });
  });

  describe('applyPlayerJoined', () => {
    it('adds a remote player when player_joined is received', () => {
      const gs = new GameState();
      gs.applyStateSync({ player: LOCAL_PLAYER, online_players: {} });
      gs.applyPlayerJoined({ id: 'p2', name: 'Bunny', x: 100, y: 200 });
      const remotes = gs.getRemotePlayers();
      expect(remotes).toHaveLength(1);
      expect(remotes[0].id).toBe('p2');
      expect(remotes[0].name).toBe('Bunny');
    });

    it('does not add local player id to remote players', () => {
      const gs = new GameState();
      gs.applyStateSync({ player: LOCAL_PLAYER, online_players: {} });
      gs.applyPlayerJoined({ id: 'p1', name: 'Kitty', x: 0, y: 0 });
      expect(gs.getRemotePlayers()).toHaveLength(0);
    });
  });

  describe('applyPlayerLeft', () => {
    it('removes a remote player when player_left is received', () => {
      const gs = new GameState();
      gs.applyStateSync({
        player: LOCAL_PLAYER,
        online_players: {
          p2: { id: 'p2', name: 'B', x: 0, y: 0, direction: 'down', character_id: 'penguin' },
        },
      });
      gs.applyPlayerLeft('p2');
      expect(gs.getRemotePlayers()).toHaveLength(0);
    });

    it('is a no-op for unknown player ids', () => {
      const gs = new GameState();
      gs.applyStateSync({ player: LOCAL_PLAYER, online_players: {} });
      expect(() => gs.applyPlayerLeft('nobody')).not.toThrow();
    });
  });

  describe('snapshotRemotePlayers', () => {
    it('returns a frozen snapshot unaffected by subsequent player_left', () => {
      const gs = new GameState();
      gs.applyStateSync({
        player: LOCAL_PLAYER,
        online_players: {
          p2: { id: 'p2', name: 'B', x: 0, y: 0, direction: 'down', character_id: 'penguin' },
        },
      });
      const snap = gs.snapshotRemotePlayers();
      gs.applyPlayerLeft('p2');
      expect(snap).toHaveLength(1);
      expect(gs.getRemotePlayers()).toHaveLength(0);
    });
  });
});
