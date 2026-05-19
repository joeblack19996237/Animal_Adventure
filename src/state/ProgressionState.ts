export interface ProgressData {
  readonly used_potion_count: number;
  readonly unique_completed_quest_ids: string[];
  readonly level: number;
  readonly unlocked_regions: string[];
}

export class ProgressionState {
  private usedPotionCount = 0;
  private uniqueCompletedQuestIds: string[] = [];
  private level = 0;
  private unlockedRegions: string[] = [];

  applyStateSync(progress: ProgressData): void {
    this.usedPotionCount = progress.used_potion_count;
    this.uniqueCompletedQuestIds = [...progress.unique_completed_quest_ids];
    this.level = progress.level;
    this.unlockedRegions = [...progress.unlocked_regions];
  }

  applyPotionUsed(): void {
    this.usedPotionCount += 1;
  }

  applyLevelUp(level: number, unlockedRegions: string[]): void {
    this.level = level;
    this.unlockedRegions = [...unlockedRegions];
  }

  getUsedPotionCount(): number {
    return this.usedPotionCount;
  }

  getUniqueCompletedQuestIds(): readonly string[] {
    return this.uniqueCompletedQuestIds;
  }

  getLevel(): number {
    return this.level;
  }

  getUnlockedRegions(): readonly string[] {
    return this.unlockedRegions;
  }

  meetsL3Conditions(): boolean {
    return this.uniqueCompletedQuestIds.length >= 2 && this.usedPotionCount >= 2;
  }
}
