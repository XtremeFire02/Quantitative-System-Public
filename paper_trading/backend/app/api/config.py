"""Bot configuration API — manage active market/strategy pairs."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel
from app.database import get_db, BotConfig
from app.config_registry import AVAILABLE_MARKETS, AVAILABLE_STRATEGIES

router = APIRouter()


@router.get("/config/available")
def get_available():
    """Return all markets and strategies the system knows about."""
    return {
        "markets": AVAILABLE_MARKETS,
        "strategies": AVAILABLE_STRATEGIES,
    }


@router.get("/config/active")
def get_active(db: Session = Depends(get_db)):
    """Return all currently active market/strategy pairs."""
    configs = db.query(BotConfig).filter(BotConfig.is_active == True).all()
    return [
        {
            "id": c.id,
            "market": c.market,
            "strategy_name": c.strategy_name,
            "is_active": c.is_active,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in configs
    ]


class AddConfigRequest(BaseModel):
    market: str
    strategy_name: str


@router.post("/config/active", status_code=201)
def add_config(req: AddConfigRequest, db: Session = Depends(get_db)):
    """Activate a market/strategy pair. Re-activates if it was previously removed."""
    if req.market not in AVAILABLE_MARKETS:
        raise HTTPException(status_code=400, detail=f"Unknown market: {req.market}")
    if req.strategy_name not in AVAILABLE_STRATEGIES:
        raise HTTPException(status_code=400, detail=f"Unknown strategy: {req.strategy_name}")

    compatible = AVAILABLE_STRATEGIES[req.strategy_name]["compatible_markets"]
    if req.market not in compatible:
        raise HTTPException(
            status_code=400,
            detail=f"{req.strategy_name} is not compatible with {req.market}. "
                   f"Compatible markets: {compatible}",
        )

    existing = db.query(BotConfig).filter(
        BotConfig.market == req.market,
        BotConfig.strategy_name == req.strategy_name,
    ).first()
    if existing:
        if existing.is_active:
            raise HTTPException(status_code=409, detail="This bot is already active.")
        existing.is_active = True
        db.commit()
        return {"status": "reactivated", "market": req.market, "strategy_name": req.strategy_name}

    try:
        db.add(BotConfig(market=req.market, strategy_name=req.strategy_name, is_active=True))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Configuration already exists.")

    return {"status": "created", "market": req.market, "strategy_name": req.strategy_name}


@router.delete("/config/active/{market}/{strategy_name}")
def remove_config(market: str, strategy_name: str, db: Session = Depends(get_db)):
    """Remove an active market/strategy pair."""
    cfg = db.query(BotConfig).filter(
        BotConfig.market == market,
        BotConfig.strategy_name == strategy_name,
    ).first()
    if not cfg:
        raise HTTPException(status_code=404, detail="Configuration not found.")
    db.delete(cfg)
    db.commit()
    return {"status": "deleted", "market": market, "strategy_name": strategy_name}
