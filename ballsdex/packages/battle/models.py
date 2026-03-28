from tortoise import fields
from tortoise.models import Model


class PlayerPosition(Model):
    """Maps a Ball (player card) to their basketball position(s)."""

    ball = fields.OneToOneField(
        "models.Ball",
        related_name="basketball_position",
        on_delete=fields.CASCADE,
    )
    primary = fields.CharField(max_length=2, description="Primary position: PG/SG/SF/PF/C")
    secondary = fields.CharField(
        max_length=2, null=True, description="Secondary position (optional)"
    )

    class Meta:
        table = "battle_playerposition"

    def allows(self, position: str) -> bool:
        """Return True if this player can play at the given position."""
        return position == self.primary or (self.secondary and position == self.secondary)

    def display(self) -> str:
        if self.secondary:
            return f"{self.primary}/{self.secondary}"
        return self.primary


class Team(Model):
    """A player's 5-man basketball team lineup."""

    player = fields.OneToOneField(
        "models.Player",
        related_name="battle_team",
        on_delete=fields.CASCADE,
    )
    pg = fields.ForeignKeyField(
        "models.BallInstance",
        null=True,
        related_name="team_pg_slot",
        on_delete=fields.SET_NULL,
    )
    sg = fields.ForeignKeyField(
        "models.BallInstance",
        null=True,
        related_name="team_sg_slot",
        on_delete=fields.SET_NULL,
    )
    sf = fields.ForeignKeyField(
        "models.BallInstance",
        null=True,
        related_name="team_sf_slot",
        on_delete=fields.SET_NULL,
    )
    pf = fields.ForeignKeyField(
        "models.BallInstance",
        null=True,
        related_name="team_pf_slot",
        on_delete=fields.SET_NULL,
    )
    c = fields.ForeignKeyField(
        "models.BallInstance",
        null=True,
        related_name="team_c_slot",
        on_delete=fields.SET_NULL,
    )

    class Meta:
        table = "battle_team"

    def is_complete(self) -> bool:
        return all([self.pg_id, self.sg_id, self.sf_id, self.pf_id, self.c_id])

    def get_slot_id(self, position: str) -> int | None:
        return {
            "PG": self.pg_id,
            "SG": self.sg_id,
            "SF": self.sf_id,
            "PF": self.pf_id,
            "C":  self.c_id,
        }.get(position.upper())

    def set_slot_id(self, position: str, value: int | None):
        pos = position.upper()
        if pos == "PG":
            self.pg_id = value
        elif pos == "SG":
            self.sg_id = value
        elif pos == "SF":
            self.sf_id = value
        elif pos == "PF":
            self.pf_id = value
        elif pos == "C":
            self.c_id = value
