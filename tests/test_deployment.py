def test_deployment_gate():

    from deployment.phase import DeploymentController

    d = DeploymentController()

    assert d.state.stage == "BACKTEST"
