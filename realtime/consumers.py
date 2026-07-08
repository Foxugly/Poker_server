"""WebSocket consumer for a Delegation Poker room (contract §2-§8).

Server is the source of truth: clients emit intentions, the server validates against
the state machine and *rebroadcasts the fact*. Vote values stay secret until reveal.
Control intentions are accepted only from the facilitator (authority, contract §0.2).
"""
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from . import services
from .services import RoomError

PROTOCOL_VERSION = 1


class RoomConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.code = self.scope["url_route"]["kwargs"]["code"].upper()
        self.group = f"room_{self.code}"
        self.joined = False
        self.token = None
        await self.accept()

    async def disconnect(self, close_code):
        if self.joined:
            participant = await self._resolve()
            if participant is not None:
                await database_sync_to_async(services.set_connected)(participant, False)
                await self._broadcast("participant.left", {"participantId": self.public_id})
                await self._broadcast_presence(participant.room)
            await self.channel_layer.group_discard(self.group, self.channel_name)

    async def receive_json(self, content, **kwargs):
        if content.get("v") != PROTOCOL_VERSION:
            return await self._error("protocol.version", "Unsupported protocol version",
                                     content.get("type"), content.get("cid"))
        mtype = content.get("type")
        payload = content.get("payload") or {}
        cid = content.get("cid")

        if mtype == "session.join":
            return await self._handle_join(payload, cid)
        if mtype == "ping":
            return await self._emit("pong", {}, cid)
        if not self.joined:
            return await self._error("token.unknown", "Join the session first", mtype, cid)

        try:
            await self._dispatch(mtype, payload, cid)
        except RoomError as exc:
            await self._error(exc.code, exc.message, exc.rejected_type or mtype, cid)

    # --- intentions -------------------------------------------------------

    async def _dispatch(self, mtype, payload, cid):
        participant = await self._resolve()
        if participant is None:
            return await self._error("token.unknown", "Unknown participant", mtype, cid)
        room = participant.room

        if mtype == "subject.set":
            text = await database_sync_to_async(services.set_subject)(room, participant, payload.get("text", ""))
            await self._broadcast("subject.updated", {"text": text})
        elif mtype == "vote.open":
            await database_sync_to_async(services.open_vote)(room, participant)
            await self._broadcast("vote.opened", {})
            await self._broadcast_participation(room)
        elif mtype == "vote.cast":
            await database_sync_to_async(services.cast_vote)(room, participant, payload.get("cardValue"))
            await self._broadcast_participation(room)
        elif mtype == "vote.reveal":
            await database_sync_to_async(services.reveal)(room, participant)
            revealed = await database_sync_to_async(services.revealed_payload)(room)
            await self._broadcast("vote.revealed", revealed)
        elif mtype == "result.act":
            chosen = await database_sync_to_async(services.act_result)(room, participant, payload.get("chosenValue"))
            await self._broadcast("result.acted", {"chosenValue": chosen})
        elif mtype == "vote.reset":
            next_state = await database_sync_to_async(services.reset_round)(room, participant)
            await self._broadcast("vote.wasReset", {"nextState": next_state})
            await self._broadcast_participation(room)
        elif mtype == "facilitator.claim":
            await self._handle_claim(participant, cid)
        else:
            await self._error("state.invalid_transition", f"Unknown type {mtype}", mtype, cid)

    async def _handle_join(self, payload, cid):
        token = payload.get("participantToken")
        participant = await self._resolve(token)
        if participant is None:
            return await self._error("token.unknown", "Unknown or expired token", "session.join", cid)
        self.token = token
        self.public_id = str(participant.public_id)
        await database_sync_to_async(services.set_connected)(participant, True)
        await self.channel_layer.group_add(self.group, self.channel_name)
        self.joined = True

        state = await database_sync_to_async(services.build_state_sync)(participant)
        await self._emit("state.sync", state, cid)
        await self._broadcast("participant.joined", {
            "participantId": self.public_id,
            "username": participant.display_name,
            "role": participant.role,
        })
        await self._broadcast_presence(participant.room)

    async def _handle_claim(self, participant, cid):
        allowed = await database_sync_to_async(services.can_claim)(participant.room)
        if not allowed:
            return await self._error("guard.inactive", "Facilitator guard not active", "facilitator.claim", cid)
        await database_sync_to_async(services.promote_facilitator)(participant.room, participant)
        await self._broadcast("facilitator.changed", {"newFacilitatorId": self.public_id})
        await self._broadcast_presence(participant.room)

    # --- helpers ----------------------------------------------------------

    async def _resolve(self, token=None):
        return await database_sync_to_async(services.resolve_participant)(self.code, token or self.token)

    async def _broadcast_participation(self, room):
        data = await database_sync_to_async(services.participation)(room)
        await self._broadcast("participation.update", data)

    async def _broadcast_presence(self, room):
        present = await database_sync_to_async(services.facilitator_present)(room)
        await self._broadcast("facilitator.presence", {"present": present})

    async def _emit(self, mtype, payload, cid=None):
        message = {"v": PROTOCOL_VERSION, "type": mtype, "payload": payload}
        if cid:
            message["cid"] = cid
        await self.send_json(message)

    async def _broadcast(self, mtype, payload):
        await self.channel_layer.group_send(
            self.group, {"type": "poker.event", "mtype": mtype, "payload": payload}
        )

    async def _error(self, code, message, rejected_type, cid):
        await self._emit("error", {
            "code": code, "message": message, "rejectedType": rejected_type, "cid": cid,
        }, cid)

    async def poker_event(self, event):
        await self._emit(event["mtype"], event["payload"])
